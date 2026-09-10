# -*- coding: utf-8 -*-
"""妙课生花 WonderKourse · FastAPI 后端

启动（VS Code 终端）：
    .venv\\Scripts\\python.exe -m uvicorn app:app --port 8000
或直接：
    .venv\\Scripts\\python.exe app.py

浏览器打开 http://127.0.0.1:8000
"""
from __future__ import annotations

import base64
import functools
import hashlib
import hmac
import html
import json
import os
import re
import shutil
import threading
import time
import uuid

from fastapi import FastAPI, File, Form, Request, Response, UploadFile
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse,
                               RedirectResponse)
from fastapi.staticfiles import StaticFiles

from agent import config
from agent import llm_client
from agent import media
from agent.orchestrator import Orchestrator, safe_slug

BASE_DIR = config.BASE_DIR
STATIC_DIR = os.path.join(BASE_DIR, "static")
OUTPUT_DIR = config.OUTPUT_DIR
UPLOAD_DIR = os.path.join(OUTPUT_DIR, "_uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = FastAPI(title="妙课生花 WonderKourse")


# ======================================================================
# 部署安全开关
# ======================================================================
def _is_local_host() -> bool:
    """是不是只监听本机（本机自用 / 云上对外，安全级别不一样）"""
    return os.environ.get("HOST", "127.0.0.1") in ("127.0.0.1", "localhost", "::1")


def web_settings_allowed() -> bool:
    """网页端「⚙ 大模型设置」是否允许写配置。

    它会往服务器上的 .env 里写 Key。本机自用很方便，但公网部署时
    任何访客都能改掉你的 Key / 接口地址（把 Base URL 指向自己的服务器，
    就能把真 Key 接走），所以：
      · 只监听本机 → 默认允许；
      · 监听 0.0.0.0 → 默认禁止，要开得显式 ALLOW_WEB_SETTINGS=1。
    """
    flag = (os.environ.get("ALLOW_WEB_SETTINGS") or "").strip()
    if flag:
        return flag.lower() not in ("0", "false", "no")
    return _is_local_host()


# ======================================================================
# 访问口令：只守「创作」这个动作
# ----------------------------------------------------------------------
# 设计取向：**浏览完全开放，创作才要口令**。
#   · 首页、使用指南、示例作品、创作台界面 —— 谁都能看，不用口令
#   · 但「开始创作」会真实吃掉 CPU（逐镜渲染 + 剪辑合成）和大模型额度，
#     所以口令卡在这一刻 —— 那才是真正值得守的地方。
#
# 门禁在服务端强制执行。「前端弹个框问口令」只是体验层，
# 就算有人绕过页面直接打接口，一样会被 401 挡回去。
#
# 为什么不用 HTTP Basic 认证让浏览器弹原生登录框：
# 那个弹窗完全依赖浏览器的实现。VS Code 内置浏览器、各类 App 的 webview
# 压根不弹，用户只会看到一行 401 的纯文本，页面上没有任何地方能输入 ——
# 这正是我们实际踩过的坑。所以自己做一套弹窗 + Cookie 会话。
# Basic 认证仍然**保留**，curl / 脚本用 -u 账号:口令 不受影响。
# ======================================================================
ACCESS_USER = os.environ.get("ACCESS_USER", "demo")
ACCESS_PASSWORD = os.environ.get("ACCESS_PASSWORD", "")

SESSION_COOKIE = "wk_pass"

# 任何情况下都不需要口令的路径
PUBLIC_PATHS = {"/login", "/logout", "/api/auth", "/api/health",
                "/favicon.ico", "/static/logo.svg"}


@functools.lru_cache(maxsize=1)
def _session_token() -> str:
    """由口令派生出会话 Cookie 的值。

    为什么不随机生成：Render 免费档闲置十几分钟就休眠，一被访问就重启，
    进程级的随机密钥会随之丢掉，用户得反复登录。由口令派生则稳定，
    服务重启后 Cookie 依然有效。

    为什么用 PBKDF2 迭代而不是一次 sha256：Cookie 万一泄露，
    攻击者可以拿它离线穷举口令，迭代 12 万次能让这种穷举贵得多。
    """
    if not ACCESS_PASSWORD:
        return ""
    return hashlib.pbkdf2_hmac(
        "sha256", ACCESS_PASSWORD.encode("utf-8"),
        b"wonderkourse-session-v1", 120_000).hex()


def _check_basic(auth: str) -> bool:
    """兼容命令行客户端：curl -u demo:口令 https://..."""
    if auth[:6].lower() != "basic ":
        return False
    try:
        raw = base64.b64decode(auth[6:]).decode("utf-8")
        user, _, pwd = raw.partition(":")
        return user == ACCESS_USER and hmac.compare_digest(pwd, ACCESS_PASSWORD)
    except Exception:
        return False


# 登录失败限流：网址可能被转发出去，得防住有人拿字典慢慢试口令
_FAIL_LOG: dict[str, list[float]] = {}
_FAIL_LIMIT = 10       # 同一 IP 连续失败达到这个次数
_FAIL_WINDOW = 600     # 就锁定这么多秒


def _client_ip(request: Request) -> str:
    """Render 这类平台会把真实客户端 IP 放在 X-Forwarded-For，取第一段"""
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "?"


def _lock_seconds(ip: str) -> int:
    """还要等几秒才能再试；0 表示没被锁"""
    now = time.time()
    hits = [t for t in _FAIL_LOG.get(ip, []) if now - t < _FAIL_WINDOW]
    _FAIL_LOG[ip] = hits
    if len(hits) < _FAIL_LIMIT:
        return 0
    return int(_FAIL_WINDOW - (now - hits[0])) + 1


def _note_fail(ip: str) -> None:
    _FAIL_LOG.setdefault(ip, []).append(time.time())


def _is_https(request: Request) -> bool:
    """服务跑在平台反代后面，看 X-Forwarded-Proto 更准"""
    return (request.url.scheme == "https"
            or "https" in request.headers.get("x-forwarded-proto", "").lower())


def _safe_next(target: str) -> str:
    """只允许跳回本站路径。

    必须挡住 //evil.com 这种「协议相对」写法，
    否则别人发个 ?next=//evil.com 的链接给你，登录后就被带去外站了。
    """
    if not target.startswith("/") or target[1:2] in ("/", "\\"):
        return "/"
    return target


# ----------------------------------------------------------------------
# 哪些动作要口令
# 用正则写成一张表，一眼能看出守的是什么，也免得以后新增接口时漏掉。
# 浏览类（GET）一律不列进来 —— 看示例、看成片、看历史项目都是公开的。
#
# 为什么 /api/settings/llm 也在这张表里：它除了检查「部署允不允许改配置」，
# 还会往服务器上的 .env 写 API Key。而「部署允不允许」的依据是
# 「服务是不是只监听本机」—— 走隧道时服务仍监听 127.0.0.1，
# 程序会误判为安全。所以必须先用口令确认身份，再看部署策略。
# ----------------------------------------------------------------------
_PROTECTED_ACTIONS = (
    ("POST",   re.compile(r"^/api/projects/?$")),               # 开始创作
    ("POST",   re.compile(r"^/api/projects/[^/]+/revise/?$")),  # 修改后重做
    ("POST",   re.compile(r"^/api/projects/[^/]+/cancel/?$")),  # 取消他人任务
    ("DELETE", re.compile(r"^/api/projects/[^/]+/?$")),         # 删除作品
    ("POST",   re.compile(r"^/api/settings/llm/?$")),           # 写 API Key
)

# 已退出的会话令牌（只存内存）。
# 为什么需要：令牌是由口令派生出来的（这样服务重启后大家的 Cookie 不会失效），
# 派生意味着它「算得出来」、服务端无状态，光删浏览器那个 Cookie 并不算数。
# 把退出过的令牌记下来，就能让它立刻作废 —— 在共用电脑上讲完课点个退出，
# 下一个人就不能顶着你的身份接着用。
#
# 两个必须知道的边界：
#   1. 有人再用口令登录时，这里会把它恢复（否刚谁都进不来）；
#   2. 服务重启会丢掉这张表 —— 这是无状态换来的代价。
# 想一次性踢掉所有人，改口令最彻底：令牌是口令派生的，一改全部失效。
_LOGGED_OUT: set[str] = set()


def _needs_pass(request: Request) -> bool:
    for method, pattern in _PROTECTED_ACTIONS:
        if request.method == method and pattern.match(request.url.path):
            return True
    return False


def _authed(request: Request) -> bool:
    """Cookie 会话或 Basic 认证任一通过即可"""
    tok = request.cookies.get(SESSION_COOKIE, "")
    if (tok and tok not in _LOGGED_OUT
            and hmac.compare_digest(tok, _session_token())):
        return True
    return _check_basic(request.headers.get("authorization", ""))


def _try_password(request: Request, password: str) -> tuple[bool, str, int]:
    """校验口令并处理失败限流。返回 (是否通过, 错误文案, 建议状态码)"""
    ip = _client_ip(request)
    wait = _lock_seconds(ip)
    if wait:
        return False, f"口令错误次数过多，请等 {wait} 秒后再试。", 429
    if not hmac.compare_digest(password or "", ACCESS_PASSWORD):
        _note_fail(ip)
        return False, "口令不对，请再试一次。", 401
    _FAIL_LOG.pop(ip, None)
    # 重新登录 = 重新启用这个令牌。
    # 必须做这一步：令牌是口令的确定函数，所有人算出来是同一个值，
    # 登出时把它拉黑，若不在这里恢复，之后任何人登录都会拿到同一个被拉黑的值，
    # 结果就是谁都进不来。
    _LOGGED_OUT.discard(_session_token())
    return True, "", 200


@app.middleware("http")
async def _access_gate(request: Request, call_next):
    """只守「创作」类动作，其余一律放行。

    放行 /api/health：它只有版本号、模型名、字体名这类信息，不含密钥，
    而云平台要靠它做健康检查（若被 401 挡住，容器会被判定不健康而反复重启）。
    """
    if not ACCESS_PASSWORD or request.url.path in PUBLIC_PATHS:
        return await call_next(request)
    if not _needs_pass(request) or _authed(request):
        return await call_next(request)

    # need_pass 是给前端看的标记：前端收到它就弹口令框，填对了自动重试原请求
    return JSONResponse(
        {"error": "这个操作需要访问口令", "need_pass": True},
        status_code=401)


# 登录页整页自带样式，不引用 /static 里的 css：
# 那些静态资源本身在门禁后面，登录前根本加载不到。
LOGIN_PAGE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>访问口令 · 妙课生花 WonderKourse</title>
<link rel="icon" href="/static/logo.svg">
<style>
  :root{
    --brand-50:#f7f4ff; --brand-600:#7c4ded; --brand-700:#6534cf;
    --bloom-50:#fff5fa; --bloom-500:#f266a2;
    --ink-900:#241a42; --ink-600:#5d4f7d; --ink-400:#7c6f9c;
    --line:rgba(124,77,237,.13); --line-strong:rgba(124,77,237,.24);
    --danger:#d23f36; --danger-soft:rgba(210,63,54,.09);
    --danger-line:rgba(210,63,54,.28);
  }
  *,*::before,*::after{box-sizing:border-box}
  body{
    margin:0;min-height:100vh;display:grid;place-items:center;padding:24px;
    font-family:"Microsoft YaHei","PingFang SC","Noto Sans CJK SC",
      system-ui,-apple-system,"Segoe UI",sans-serif;
    color:var(--ink-900);-webkit-font-smoothing:antialiased;
    background:
      radial-gradient(880px 480px at 12% -12%,rgba(124,77,237,.17),transparent 62%),
      radial-gradient(720px 460px at 102% 112%,rgba(242,102,162,.17),transparent 62%),
      linear-gradient(160deg,var(--brand-50),var(--bloom-50));
  }
  .card{
    width:100%;max-width:404px;background:#fff;border:1px solid var(--line);
    border-radius:22px;padding:40px 36px 32px;text-align:center;
    box-shadow:0 24px 60px -18px rgba(52,33,105,.22),0 2px 8px rgba(52,33,105,.05);
    animation:rise .5s cubic-bezier(.22,.9,.29,1) both;
  }
  @keyframes rise{from{opacity:0;transform:translateY(14px)}to{opacity:1;transform:none}}
  @media (prefers-reduced-motion:reduce){.card{animation:none}}
  .logo{display:block;width:60px;height:60px;margin:0 auto 18px;
    filter:drop-shadow(0 8px 18px rgba(124,77,237,.28))}
  h1{margin:0;font-size:26px;letter-spacing:.5px;
    background:linear-gradient(96deg,var(--brand-600),var(--bloom-500));
    -webkit-background-clip:text;background-clip:text;color:transparent}
  .brand-en{margin:6px 0 0;font-size:12px;letter-spacing:2.4px;
    text-transform:uppercase;color:var(--ink-400)}
  .lede{margin:22px 0 0;font-size:14.5px;line-height:1.75;color:var(--ink-600)}
  .err{margin:20px 0 0;padding:11px 14px;border-radius:11px;font-size:13.5px;
    color:var(--danger);background:var(--danger-soft);
    border:1px solid var(--danger-line)}
  form{margin-top:24px;text-align:left}
  label{display:block;font-size:13px;font-weight:600;
    color:var(--ink-600);margin-bottom:8px}
  input[type=password]{
    width:100%;padding:13px 15px;font-size:15px;font-family:inherit;
    color:var(--ink-900);background:#fbfaff;border:1.5px solid var(--line-strong);
    border-radius:12px;outline:none;
    transition:border-color .18s,box-shadow .18s,background .18s;
  }
  input[type=password]::placeholder{color:#a99fc4}
  input[type=password]:focus{background:#fff;border-color:var(--brand-600);
    box-shadow:0 0 0 4px rgba(124,77,237,.14)}
  button{
    width:100%;margin-top:16px;padding:13px 18px;font-size:15px;font-weight:600;
    font-family:inherit;color:#fff;cursor:pointer;border:0;border-radius:12px;
    background:linear-gradient(96deg,var(--brand-600),var(--brand-700));
    box-shadow:0 8px 20px -6px rgba(124,77,237,.55);
    transition:transform .16s,box-shadow .16s,filter .16s;
  }
  button:hover{transform:translateY(-1px);filter:brightness(1.06);
    box-shadow:0 12px 26px -8px rgba(124,77,237,.6)}
  button:active{transform:translateY(0)}
  .foot{margin:22px 0 0;padding-top:18px;border-top:1px solid var(--line);
    font-size:12.5px;line-height:1.7;color:var(--ink-400)}
</style>
</head>
<body>
<main class="card">
  <img class="logo" src="/static/logo.svg" alt="妙课生花" width="60" height="60">
  <h1>妙课生花</h1>
  <p class="brand-en">WonderKourse</p>
  <p class="lede">这个站点需要一个访问口令才能进入。<br>口令请向把网址分享给你的人索取。</p>
  __ERROR__
  <form method="post" action="/login">
    <input type="hidden" name="next" value="__NEXT__">
    <label for="pw">访问口令</label>
    <input id="pw" name="password" type="password" required autofocus
           autocomplete="current-password" placeholder="请输入口令">
    <button type="submit">进入实验室</button>
  </form>
  <p class="foot">口令仅用于验证身份，不会上传或记录。</p>
</main>
</body>
</html>
"""


def _render_login(next_url: str = "/", error: str = "") -> HTMLResponse:
    page = LOGIN_PAGE.replace("__NEXT__", html.escape(next_url, quote=True))
    page = page.replace("__ERROR__",
                        f'<p class="err" role="alert">{html.escape(error)}</p>'
                        if error else "")
    return HTMLResponse(page, headers={"Cache-Control": "no-store"})


@app.get("/login")
def login_page(request: Request, next: str = "/"):
    # 已经登录过就别再看登录页了
    if hmac.compare_digest(request.cookies.get(SESSION_COOKIE, ""),
                           _session_token()):
        return RedirectResponse(_safe_next(next), status_code=303)
    return _render_login(_safe_next(next))


def _set_session(resp: Response, request: Request) -> Response:
    resp.set_cookie(
        SESSION_COOKIE, _session_token(),
        max_age=30 * 24 * 3600, path="/",
        httponly=True, samesite="lax", secure=_is_https(request),
    )
    return resp


@app.post("/login")
async def do_login(request: Request, password: str = Form(""),
                   next: str = Form("/")):
    """独立登录页的提交入口（直接用浏览器打开 /login 时用）"""
    if not ACCESS_PASSWORD:
        return RedirectResponse("/", status_code=303)
    ok, err, _ = _try_password(request, password)
    if not ok:
        return _render_login(_safe_next(next), err)
    return _set_session(RedirectResponse(_safe_next(next), status_code=303),
                        request)


@app.get("/api/auth")
def auth_state(request: Request):
    """前端靠它决定：要不要弹口令框、顶栏按钮该显示什么。

    只暴露「要不要口令」和「当前是否已通过」，不泄露口令本身。
    """
    return {"required": bool(ACCESS_PASSWORD), "authed": _authed(request)}


@app.post("/api/auth")
async def do_auth(request: Request, password: str = Form("")):
    """弹窗提交口令走这里：返回 JSON，前端不用跟 303 跳转打交道"""
    if not ACCESS_PASSWORD:
        return {"ok": True}
    ok, err, status = _try_password(request, password)
    if not ok:
        return JSONResponse({"error": err}, status_code=status)
    return _set_session(JSONResponse({"ok": True}), request)


@app.get("/logout")
def logout():
    # 光删浏览器那个 Cookie 不够：令牌是算得出来的，拿到过它的人还能接着用。
    # 记下这个令牌，让它立即失效。
    tok = _session_token()
    if tok:
        _LOGGED_OUT.add(tok)
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp


@app.get("/favicon.ico")
def favicon():
    """浏览器总会来要这个，指到 logo 上，省得日志里刷 404"""
    return RedirectResponse("/static/logo.svg", status_code=307)


@app.middleware("http")
async def _no_cache_static(request, call_next):
    """静态资源强制协商缓存：改了 css/js 刷新即生效，不会被浏览器内存缓存吃掉"""
    resp = await call_next(request)
    path = request.url.path
    if path.startswith("/static/") or path in ("/", "/guide", "/create", "/login"):
        resp.headers["Cache-Control"] = "no-cache, must-revalidate"
    return resp


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

ALLOWED_EXT = {".pdf", ".ppt", ".pptx", ".doc", ".docx", ".txt", ".md"}
MAX_UPLOAD_MB = 30   # 单份文档上限。上传接口不需要口令，总得有个封顶

# ----------------------------------------------------------------------
# 内存任务表：project_id -> {status, events[], result, error, cancel}
# events 是一个「只追加」的事件流，前端用 since 下标增量拉取，
# 从而实现不做 WebSocket 也能获得实时的 Agent 执行过程。
# ----------------------------------------------------------------------
TASKS: dict[str, dict] = {}
LOCK = threading.Lock()


def _task(pid: str) -> dict | None:
    with LOCK:
        return TASKS.get(pid)


def _push(pid: str, event: dict) -> None:
    with LOCK:
        t = TASKS.get(pid)
        if t is not None:
            t["events"].append(event)


def _now() -> str:
    return time.strftime("%H:%M:%S")


def _cb(pid: str, agent_key: str):
    """生成一个只写日志的回调，供各 Agent 使用"""
    return lambda level, msg: _push(pid, {"type": "log", "level": level,
                                          "agent": agent_key, "msg": msg,
                                          "t": _now()})


def _read_json(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _write_json(path: str, data) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)


# ======================================================================
# 制作任务
# ======================================================================
def _worker(pid: str, topic: str, files: list, opts: dict,
            cancel: threading.Event) -> None:
    with LOCK:
        TASKS[pid]["status"] = "running"
        TASKS[pid]["started"] = time.time()

    def emit(event: dict) -> None:
        _push(pid, event)

    try:
        orch = Orchestrator()
        result = orch.run(
            topic, files=files, source_text=opts.get("source_text", ""),
            audience=opts.get("audience", "本科生"),
            minutes=float(opts.get("minutes", 4)),
            style=opts.get("style", "calm"),
            theme=opts.get("theme", "deepsea"),
            fmt=opts.get("fmt", "landscape"),
            illustrations=opts.get("illustrations"),
            pid=pid, emit=emit, should_stop=cancel.is_set)
        with LOCK:
            TASKS[pid]["status"] = "done"
            TASKS[pid]["result"] = result
    except Exception as e:                      # noqa: BLE001
        import traceback
        _push(pid, {"type": "log", "level": "warning", "agent": "orchestrator",
                    "msg": f"制作失败：{e}", "t": _now()})
        with LOCK:
            TASKS[pid]["status"] = "error"
            TASKS[pid]["error"] = str(e)
            TASKS[pid]["traceback"] = traceback.format_exc()
    finally:
        for f in files:                         # 清理上传的临时文件
            try:
                os.remove(f["path"])
            except OSError:
                pass


# ======================================================================
# 页面
# ======================================================================
@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/create")
def create_page():
    return FileResponse(os.path.join(STATIC_DIR, "create.html"))


@app.get("/guide")
def guide_page():
    return FileResponse(os.path.join(STATIC_DIR, "guide.html"))


# ======================================================================
# 能力探测
# ======================================================================
@app.get("/api/health")
def health():
    return {
        "ok": True,
        "version": "WonderKourse 1.0",
        # 部署标识：云平台构建时会注入 commit 号（Render 是 RENDER_GIT_COMMIT）。
        # 本机跑显示 local。作用是「外面不用登录就能确认新代码到底部署上去了没」——
        # 否则整个站点都被口令挡着，无法从外部验证版本。
        "build": (os.environ.get("RENDER_GIT_COMMIT")
                  or os.environ.get("GIT_COMMIT")
                  or os.environ.get("SOURCE_VERSION") or "local")[:7],
        "llm_mode": llm_client.llm_label(),
        "llm_ready": llm_client.llm_available(),
        # 前端靠它决定顶栏显示「登录 / 注册」还是「退出登录」：
        # 本机自用没口令，公网部署有。这里只暴露「要不要口令」，不泄露口令本身。
        "auth_required": bool(ACCESS_PASSWORD),
        "ffmpeg": media.ffmpeg_version(),
        "subtitle_filter": media.has_filter("subtitles"),
        "font": os.path.basename(config.font_path(False) or "") or "未找到",
        "tts_voice": config.TTS_VOICE,
        "resolution": f"{config.WIDTH}×{config.HEIGHT}",
        "illustrations": config.ILLUSTRATIONS,
        "formats": [{"key": k, "name": v["name"], "desc": v["desc"]}
                    for k, v in config.FORMATS.items()],
        "themes": [{"key": k, "name": v["name"]} for k, v in config.THEMES.items()],
        "presets": [
            "生成式AI如何赋能教学设计", "布鲁姆教育目标分类学", "什么是大语言模型",
            "ADDIE 教学设计模型", "翻转课堂", "核心素养导向的教学",
        ],
    }


# ======================================================================
# 文档上传（正式解析发生在制作流程的第 ① 步，这里只做即时预检）
# ======================================================================
@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    name = file.filename or "document"
    ext = os.path.splitext(name)[1].lower()
    if ext not in ALLOWED_EXT:
        return JSONResponse(
            {"error": f"暂不支持 {ext} 格式，请上传 PDF / Word / PPT / TXT"},
            status_code=400)
    # 分块读取 + 限总量。这个接口不需要口令，不能让人丢个几 GB 的文件
    # 过来把内存吃光（云上免费档只有 512MB）。
    buf = bytearray()
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        buf.extend(chunk)
        if len(buf) > MAX_UPLOAD_MB * 1024 * 1024:
            return JSONResponse(
                {"error": f"文件超过 {MAX_UPLOAD_MB} MB 上限"}, status_code=413)
    if not buf:
        return JSONResponse({"error": "文件为空"}, status_code=400)
    data = bytes(buf)

    fid = uuid.uuid4().hex[:12]
    path = os.path.join(UPLOAD_DIR, f"{fid}{ext}")
    with open(path, "wb") as f:
        f.write(data)

    from agent.agents import DocumentParserAgent
    try:
        info = DocumentParserAgent().parse(path)
    except Exception as e:                      # noqa: BLE001
        return JSONResponse({"error": f"解析失败：{e}"}, status_code=400)

    return {"file_id": fid, "name": name, "size_kb": round(len(data) / 1024, 1),
            "chars": info["chars"], "meta": info["meta"],
            "keywords": info["keywords"][:8], "preview": info["text"][:400]}


# ======================================================================
# 创建制作任务
# ======================================================================
@app.post("/api/projects")
async def create_project(
        topic: str = Form(""),
        file_ids: str = Form(""),
        source_text: str = Form(""),
        audience: str = Form("本科生"),
        minutes: float = Form(4.0),
        style: str = Form("calm"),
        theme: str = Form("deepsea"),
        fmt: str = Form("landscape"),
        illustrations: str = Form("")):
    topic = (topic or "").strip()
    ids = [i.strip() for i in (file_ids or "").split(",") if i.strip()]
    if not topic and not ids:
        return JSONResponse({"error": "请输入知识主题，或至少上传一份文档"},
                            status_code=400)
    if not topic:
        topic = "文档精讲"

    files = []
    for base in ids:
        for ext in ALLOWED_EXT:
            p = os.path.join(UPLOAD_DIR, base + ext)
            if os.path.exists(p):
                files.append({"path": p, "name": os.path.basename(p)})
                break

    pid = f"{time.strftime('%Y%m%d-%H%M%S')}-{safe_slug(topic)}"
    with LOCK:
        TASKS[pid] = {"status": "queued", "events": [], "result": None,
                      "error": None, "topic": topic, "started": time.time(),
                      "files": [f["name"] for f in files],
                      "cancel": threading.Event()}

    opts = {"source_text": source_text, "audience": audience, "minutes": minutes,
            "style": style, "theme": theme, "fmt": fmt,
            "illustrations": (None if illustrations == ""
                              else illustrations not in ("0", "false", "False"))}
    threading.Thread(target=_worker, args=(pid, topic, files, opts,
                                           TASKS[pid]["cancel"]),
                     daemon=True).start()
    return {"project_id": pid, "topic": topic, "files": len(files)}


@app.post("/api/projects/{pid}/cancel")
def cancel_project(pid: str):
    with LOCK:
        t = TASKS.get(pid)
        if t and t.get("cancel"):
            t["cancel"].set()
    return {"ok": True}


# ======================================================================
# 实时事件流
# ======================================================================
@app.get("/api/projects/{pid}/events")
def project_events(pid: str, since: int = 0):
    with LOCK:
        t = TASKS.get(pid)
        if t is None:
            return JSONResponse(
                {"error": "任务不在本次服务进程中（服务可能重启过），"
                          "请从「历史项目」查看已完成的成片。"},
                status_code=404)
        return {
            "status": t["status"],
            "events": t["events"][since:],
            "total": len(t["events"]),
            "error": t["error"],
            "result": t["result"] if t["status"] == "done" else None,
            "topic": t["topic"],
        }


@app.get("/api/projects/{pid}/status")
def project_status(pid: str):
    t = _task(pid)
    with LOCK:
        if t is None:
            return JSONResponse({"error": "任务不存在"}, status_code=404)
        return {"status": t["status"], "error": t["error"],
                "result": t["result"], "events": len(t["events"])}


# ======================================================================
# 历史项目
# ======================================================================
@app.get("/api/projects")
def list_projects():
    items = []
    if os.path.isdir(OUTPUT_DIR):
        for name in sorted(os.listdir(OUTPUT_DIR), reverse=True):
            pdir = os.path.join(OUTPUT_DIR, name)
            if not os.path.isdir(pdir) or name.startswith("_"):
                continue
            meta = _read_json(os.path.join(pdir, "project.json"))
            plan = _read_json(os.path.join(pdir, "plan.json"))
            done = os.path.exists(os.path.join(pdir, "final.mp4"))
            items.append({
                "id": name,
                "title": meta.get("title") or plan.get("title") or name,
                "subject": meta.get("subject") or plan.get("subject", ""),
                "created": name.split("-")[0] if "-" in name else name,
                "shots": len(meta.get("shots") or plan.get("shots") or []),
                "duration": meta.get("duration", 0),
                "score": (meta.get("review") or {}).get("score"),
                "theme": meta.get("theme", "deepsea"),
                "fmt": meta.get("fmt", "landscape"),
                "resolution": meta.get("resolution", ""),
                "done": done,
                "live": bool(_task(name)),
            })
    return {"items": items}


@app.delete("/api/projects/{pid}")
def delete_project(pid: str):
    """删除一个历史项目（连 output/<项目号>/ 整个目录一起删）。

    首页「示例作品」读的是同一个 /api/projects 接口，
    所以这里删掉之后，首页刷新（或切回标签页）就自然同步消失了。
    """
    name = os.path.basename(pid or "").strip()
    # 两道防线（原来都没有，都是真问题）：
    #   1) 下划线开头的是内部目录 —— output/_uploads 存的是上传的原始文档，
    #      它也是个目录，不拦的话会被当成项目整个删掉
    #   2) 正在生成的项目不能删，否则后台线程会往一个已消失的目录里继续写
    if not name or name.startswith("_"):
        return JSONResponse({"error": "该项目不可删除"}, status_code=400)
    pdir = os.path.join(OUTPUT_DIR, name)
    if not os.path.isdir(pdir):
        return JSONResponse({"error": "项目不存在"}, status_code=404)
    t = _task(name)
    if t and t.get("status") == "running":
        return JSONResponse({"error": "该项目正在生成中，请等它完成或先取消再删"},
                            status_code=409)
    try:
        shutil.rmtree(pdir)          # 不用 ignore_errors：删不掉要如实报错
    except OSError as e:
        return JSONResponse({"error": f"删除失败：{e}"}, status_code=500)
    with LOCK:
        TASKS.pop(name, None)
    return {"ok": True, "id": name}


# ======================================================================
# 项目详情与产物
# ======================================================================
@app.get("/api/projects/{pid}/detail")
def project_detail(pid: str):
    pdir = os.path.join(OUTPUT_DIR, os.path.basename(pid))
    meta = _read_json(os.path.join(pdir, "project.json"))
    plan = _read_json(os.path.join(pdir, "plan.json"))
    if not meta and not plan:
        return JSONResponse({"error": "项目不存在"}, status_code=404)

    shots = meta.get("shots") or plan.get("shots") or []
    frames_dir = os.path.join(pdir, "frames")
    images = []
    if os.path.isdir(frames_dir):
        # 只认 shot_*.png，避免任何临时图片混进分镜时间轴
        images = sorted(f for f in os.listdir(frames_dir)
                        if f.startswith("shot_") and f.endswith(".png"))

    # 每个分镜在成片时间轴上的起点（点击分镜卡片跳转回放）
    play_at, t = [], 0.0
    for s in shots:
        play_at.append(round(t, 2))
        t += float(s.get("seconds") or 0) + config.SHOT_GAP

    return {
        "id": pid,
        "title": meta.get("title") or plan.get("title") or pid,
        "subject": meta.get("subject") or plan.get("subject", ""),
        "source": meta.get("source") or plan.get("source", ""),
        "keywords": meta.get("keywords") or plan.get("keywords", []),
        "minutes": meta.get("minutes") or plan.get("minutes"),
        "shots": shots,
        "outline": plan.get("outline", []),
        "images": images,
        "playAt": play_at,
        "review": meta.get("review"),
        "review_rounds": meta.get("review_rounds", []),
        "duration": meta.get("duration"),
        "size_mb": meta.get("size_mb"),
        "documents": meta.get("documents", []),
        "engine": meta.get("engine", []),
        "theme": meta.get("theme", "deepsea"),
        "fmt": meta.get("fmt", "landscape"),
        "has_video": os.path.exists(os.path.join(pdir, "final.mp4")),
        "has_nosub": os.path.exists(os.path.join(pdir, "final_nosub.mp4")),
        "srt": os.path.exists(os.path.join(pdir, "narration.srt")),
        "ass": os.path.exists(os.path.join(pdir, "narration.ass")),
    }


@app.get("/api/projects/{pid}/video")
def project_video(pid: str, subs: int = 1):
    pdir = os.path.join(OUTPUT_DIR, os.path.basename(pid))
    path = os.path.join(pdir, "final.mp4" if subs else "final_nosub.mp4")
    if not os.path.exists(path):
        path = os.path.join(pdir, "final.mp4")
    if os.path.exists(path):
        return FileResponse(path, media_type="video/mp4",
                            filename=f"{pid}{'' if subs else '_nosub'}.mp4")
    return JSONResponse({"error": "视频尚未生成"}, status_code=404)


@app.get("/api/projects/{pid}/srt")
def project_srt(pid: str):
    path = os.path.join(OUTPUT_DIR, os.path.basename(pid), "narration.srt")
    if os.path.exists(path):
        return FileResponse(path, media_type="application/x-subrip",
                            filename=f"{pid}.srt")
    return JSONResponse({"error": "字幕不存在"}, status_code=404)


@app.get("/api/projects/{pid}/frames/{filename}")
def project_frame(pid: str, filename: str):
    path = os.path.join(OUTPUT_DIR, os.path.basename(pid), "frames",
                        os.path.basename(filename))
    if os.path.exists(path):
        return FileResponse(path, media_type="image/png")
    return JSONResponse({"error": "画面不存在"}, status_code=404)


# ======================================================================
# 少量干预点：预览后「改配色 / 改文案」并定向重做成片
# ======================================================================
def _existing_metas(plan: dict, pdir: str) -> list:
    """复用已生成的音轨，避免无谓重跑 TTS"""
    metas = []
    for s in plan["shots"]:
        p = os.path.join(pdir, "shots", f"shot_{s['index']:02d}.mp3")
        if not os.path.exists(p):
            return []
        metas.append({"index": s["index"], "path": p,
                      "duration": media.probe_duration(p), "engine": "reuse",
                      "scene": s["scene"], "text": s["narration"]})
    return metas


def _revise_worker(pid: str, pdir: str, theme: str, edits: list) -> None:
    """只重做受影响的部分：改文案 → 重配音+重建字幕；改配色 → 重渲染画面；
    最后统一重新剪辑合成并再次质检。事件流与首次制作一致，前端无需特殊处理。"""
    from agent import agents as AG
    from agent import music

    def emit(e: dict) -> None:
        _push(pid, e)

    try:
        plan = _read_json(os.path.join(pdir, "plan.json"))
        if not plan:
            raise RuntimeError("找不到该项目的脚本（plan.json）")
        meta = _read_json(os.path.join(pdir, "project.json"))
        shots = plan["shots"]
        by_index = {s["index"]: s for s in shots}

        emit({"type": "start", "project_id": pid, "topic": plan.get("title", ""),
              "steps": AG.AGENT_SPECS})
        emit({"type": "log", "level": "info", "agent": "orchestrator",
              "msg": "进入人工干预：按你的修改定向重做（只重跑受影响的环节）",
              "t": _now()})

        changed = []
        for ed in edits:
            idx = int(ed.get("index", 0))
            text = (ed.get("narration") or "").strip()
            if idx in by_index and text and text != by_index[idx]["narration"]:
                by_index[idx]["narration"] = text
                changed.append(idx)

        theme = theme or meta.get("theme") or "deepsea"
        old_theme = meta.get("theme") or "deepsea"
        fmt = meta.get("fmt") or plan.get("fmt") or "landscape"
        ill = meta.get("illustrations")
        orch = Orchestrator()

        # ① 语音：只重做被改动的分镜，其余复用已有音轨
        if changed:
            emit({"type": "log", "level": "行动", "agent": "audio",
                  "msg": f"重做分镜 {changed} 的配音（其余音轨复用）", "t": _now()})
            base = _existing_metas(plan, pdir)
            metas, _bgm = orch.audio.synthesize(plan, pdir, _cb(pid, "audio"),
                                                retry_shots=changed, base_metas=base,
                                                fmt=fmt)
        else:
            emit({"type": "log", "level": "思考", "agent": "audio",
                  "msg": "旁白未改动，复用已有配音", "t": _now()})
            metas = [{"index": s["index"],
                      "path": os.path.join(pdir, "shots", f"shot_{s['index']:02d}.mp3"),
                      "duration": float(s.get("seconds") or 0), "engine": "reuse",
                      "scene": s["scene"], "text": s["narration"]} for s in shots]
            for m in metas:
                m["duration"] = media.probe_duration(m["path"]) or m["duration"]
            orch.audio.build_srt(metas, pdir, fmt=fmt)
            _bgm = None

        # ② 画面：配色变化或画面缺失才重渲染（Pillow 渲染很快）
        frames_dir = os.path.join(pdir, "frames")
        frames = sorted(f for f in os.listdir(frames_dir)
                        if f.endswith(".png")) if os.path.isdir(frames_dir) else []
        if theme != old_theme or len(frames) != len(shots):
            images = orch.visual.render(plan, pdir, _cb(pid, "visual"), theme=theme,
                                        fmt=fmt, illustrations=ill)
        else:
            images = [os.path.join(frames_dir, f) for f in frames]
            emit({"type": "log", "level": "思考", "agent": "visual",
                  "msg": "配色未变，直接复用已有画面", "t": _now()})

        # ③ 背景音乐
        if config.BGM_ENABLED:
            total = sum(m["duration"] for m in metas) + config.SHOT_GAP * len(metas)
            _bgm = music.build_bgm(total, os.path.join(pdir, "bgm.wav"),
                                   style=plan.get("style", "calm"))

        # ④ 重新剪辑 + 质检
        result = orch.edit.compose(images, metas, pdir, _cb(pid, "edit"),
                                   True, _bgm, tag="revise", fmt=fmt)
        review = orch.review.review(plan, images, metas, result, _cb(pid, "review"))
        review["round"] = len(meta.get("review_rounds") or []) + 1
        rounds = (meta.get("review_rounds") or []) + [review]

        final = dict(meta)
        final.update({
            "theme": theme, "fmt": fmt, "shots": shots,
            "duration": result["duration"],
            "size_mb": round(os.path.getsize(result["final"]) / 1024 / 1024, 2),
            "review": review, "review_rounds": rounds,
            "minutes": round(sum(m["duration"] for m in metas) / 60.0, 1),
            "images": sorted(f for f in os.listdir(frames_dir)
                             if f.startswith("shot_") and f.endswith(".png")),
        })
        _write_json(os.path.join(pdir, "project.json"), final)
        _write_json(os.path.join(pdir, "plan.json"), plan)
        emit({"type": "review", **review})
        emit({"type": "result", "data": final})
        with LOCK:
            TASKS[pid]["status"] = "done"
            TASKS[pid]["result"] = final
    except Exception as e:                      # noqa: BLE001
        import traceback
        emit({"type": "log", "level": "warning", "agent": "orchestrator",
              "msg": f"重做失败：{e}", "t": _now()})
        with LOCK:
            TASKS[pid]["status"] = "error"
            TASKS[pid]["error"] = str(e)
            TASKS[pid]["traceback"] = traceback.format_exc()


@app.post("/api/projects/{pid}/revise")
def revise_project(pid: str, theme: str = Form(""), edits: str = Form("")):
    pdir = os.path.join(OUTPUT_DIR, os.path.basename(pid))
    if not os.path.isdir(pdir):
        return JSONResponse({"error": "项目不存在"}, status_code=404)
    try:
        edit_list = json.loads(edits) if edits.strip() else []
    except Exception:
        return JSONResponse({"error": "edits 不是合法 JSON"}, status_code=400)

    with LOCK:
        t = TASKS.get(pid)
        if t and t.get("status") == "running":
            return JSONResponse({"error": "该项目正在制作中，请稍候"}, status_code=409)
        TASKS[pid] = {"status": "running", "events": [], "result": None,
                      "error": None, "topic": pid, "started": time.time(),
                      "cancel": threading.Event()}

    threading.Thread(target=_revise_worker, args=(pid, pdir, theme, edit_list),
                     daemon=True).start()
    return {"project_id": pid, "revision": True}


# ======================================================================
# 可选：保存大模型配置（写入 .env，立即生效，无需重启）
# ======================================================================
@app.post("/api/settings/llm")
def save_llm(api_key: str = Form(""), base_url: str = Form(""),
             model: str = Form(""), voice: str = Form("")):
    if not web_settings_allowed():
        return JSONResponse(
            {"error": "线上部署已禁用网页改配置，请在平台的环境变量里设置 "
                      "LLM_API_KEY / LLM_MODEL"},
            status_code=403)
    env_path = os.path.join(BASE_DIR, ".env")
    current = {}
    if os.path.exists(env_path):
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, _, v = line.partition("=")
                    current[k.strip()] = v.strip()
    if api_key.strip():
        current["LLM_API_KEY"] = api_key.strip()
    if base_url.strip():
        current["LLM_BASE_URL"] = base_url.strip()
    if model.strip():
        current["LLM_MODEL"] = model.strip()
    if voice.strip():
        current["TTS_VOICE"] = voice.strip()
    with open(env_path, "w", encoding="utf-8") as f:
        for k, v in current.items():
            f.write(f"{k}={v}\n")
    os.environ.update(current)
    config.refresh()
    return {"ok": True, "llm_mode": llm_client.llm_label()}


if __name__ == "__main__":
    import uvicorn
    # 本机跑默认 127.0.0.1:8000；容器 / 云平台靠 HOST / PORT 环境变量
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    shown = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    print("=" * 62)
    print("  妙课生花 WonderKourse · 让创意开成一堂课")
    print(f"  脚本来源：{llm_client.llm_label()}")
    print(f"  FFmpeg ：{media.ffmpeg_version()}")
    print(f"  中文字体：{os.path.basename(config.font_path(False) or '') or '未找到（画面中文会变方块）'}")
    print(f"  监听    ：{host}:{port}")
    print(f"  浏览器访问： http://{shown}:{port}")
    print("=" * 62)
    uvicorn.run(app, host=host, port=port)
