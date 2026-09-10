# -*- coding: utf-8 -*-
"""访问口令 · 端到端回归测试

验证的设计取向是「浏览开放，创作才要口令」：
  · 首页 / 指南 / 创作台 / 示例作品 / 成片 / 看板 —— 不要口令，谁都能看
  · 开始创作 / 修改后重做 / 取消任务 / 删除作品 —— 要口令

不依赖任何第三方库（只用标准库 http.client），也不产生任何副作用：
所有写操作都故意用会「提前失败」的参数（空主题、不存在的项目号），
既能确认口令闸门放行了，又不会真的启动一次视频生成。

用法（在项目根目录）：
    # 先起一个带口令的实例
    $env:HOST='127.0.0.1'; $env:PORT='8001'; $env:ACCESS_PASSWORD='你设的口令'
    .\\.venv\\Scripts\\python.exe app.py

    # 另开一个终端跑测试
    python tools\\test_auth.py

可用环境变量：TEST_HOST（默认 127.0.0.1）、TEST_PORT（默认 8001）、
TEST_PASSWORD（默认 wk-demo-2026）—— 要跟服务端 ACCESS_PASSWORD 一致。

注意：最后两项会故意连续输错口令触发限流，会把本机 IP 锁 10 分钟，
所以放在最后；测完建议重启服务清掉锁定状态。
"""
import base64
import http.client
import os
import sys
import urllib.parse

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HOST = os.environ.get("TEST_HOST", "127.0.0.1")
PORT = int(os.environ.get("TEST_PORT", "8001"))
PW = os.environ.get("TEST_PASSWORD", "wk-demo-2026")

# 一个不存在的项目号：带口令访问会走到 404，既能证明闸门放行，
# 又绝不会误删任何真实数据（删除接口有下划线保护 + 目录存在性检查）
GHOST = "no-such-project-xyz"

results = []


def req(method, path, body=None, headers=None, cookie=None):
    """发一个请求。http.client 不跟重定向，正好用来观察 303。"""
    h = dict(headers or {})
    if cookie:
        h["Cookie"] = cookie
    if body is not None:
        h.setdefault("Content-Type", "application/x-www-form-urlencoded")
    c = http.client.HTTPConnection(HOST, PORT, timeout=20)
    c.request(method, path, body=body, headers=h)
    r = c.getresponse()
    data = r.read().decode("utf-8", "replace")
    status, hdrs = r.status, {k.lower(): v for k, v in r.getheaders()}
    c.close()
    return status, hdrs, data


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(f"{'PASS' if cond else 'FAIL'}  {name}" + (f"   [{detail}]" if detail else ""))


print("=" * 70)
print(f"  访问口令回归测试  ->  {HOST}:{PORT}")
print("  设计：浏览开放，创作才要口令")
print("=" * 70)

# ============================================================
# 一、浏览：全部不要口令
# ============================================================
print("-- 一、浏览时代（不带任何凭证）--")

for path, label in (("/", "首页"), ("/guide", "使用指南"), ("/create", "创作台")):
    st, hd, _ = req("GET", path)
    check(f"1  未登录可访问{label} {path}", st == 200, f"HTTP {st}")

st, hd, _ = req("GET", "/static/css/style.css")
check("2  静态资源公开", st == 200, f"HTTP {st}")

st, hd, body = req("GET", "/api/projects")
check("3  示例作品列表公开（可直接看）", st == 200, f"HTTP {st}")

st, hd, _ = req("GET", "/api/health")
check("4  健康检查公开", st == 200, f"HTTP {st}")

st, hd, _ = req("GET", "/favicon.ico")
check("5  favicon 指向 logo", st == 307 and hd.get("location") == "/static/logo.svg",
      f"HTTP {st} -> {hd.get('location')}")

st, hd, body = req("GET", "/api/auth")
check("6  /api/auth 公开且正确报状态",
      st == 200 and '"required":true' in body.replace(" ", "")
      and '"authed":false' in body.replace(" ", ""),
      body[:60])

# ============================================================
# 二、创作：需要口令
# ============================================================
print("-- 二、创作类动作（不带任何凭证，应当被拦）--")

st, hd, body = req("POST", "/api/projects", body="topic=&file_ids=")
check("7  开始创作被拦 -> 401", st == 401, f"HTTP {st}")
check("8  401 带 need_pass 标记（前端据此弹口令框）", "need_pass" in body, body[:70])

st, hd, _ = req("POST", f"/api/projects/{GHOST}/revise", body="theme=&edits=[]")
check("9  修改后重做被拦 -> 401", st == 401, f"HTTP {st}")

st, hd, _ = req("POST", f"/api/projects/{GHOST}/cancel")
check("10 取消任务被拦 -> 401", st == 401, f"HTTP {st}")

st, hd, _ = req("DELETE", f"/api/projects/{GHOST}")
check("11 删除作品被拦 -> 401", st == 401, f"HTTP {st}")

st, hd, _ = req("POST", "/api/settings/llm", body="api_key=sk-evil")
check("12 改大模型配置被拦 -> 401", st == 401, f"HTTP {st}")
# ============================================================
# 三、拿口令
# ============================================================
print("-- 三、口令获取（弹窗与独立登录页）--")

st, hd, body = req("GET", "/login")
check("13 独立登录页仍可用（页面上有输入框）",
      st == 200 and 'type="password"' in body, f"HTTP {st}")

st, hd, body = req("POST", "/api/auth", body="password=wrong-password")
check("14 弹窗接口：错口令 -> 401", st == 401, f"HTTP {st}")

st, hd, body = req("POST", "/api/auth",
                   body="password=" + urllib.parse.quote(PW))
sc = hd.get("set-cookie", "")
check("15 弹窗接口：对口令 -> 200 + 下发 Cookie",
      st == 200 and sc.startswith("wk_pass="), f"HTTP {st} {sc[:32]}")
check("16 Cookie 带 HttpOnly", "httponly" in sc.lower())
check("17 Cookie 带 SameSite=Lax", "samesite=lax" in sc.lower())
check("18 本地 http 下不带 Secure（否则写不进浏览器）",
      "; secure" not in sc.lower())

cookie = sc.split(";")[0]

st, hd, body = req("GET", "/api/auth", cookie=cookie)
check("19 带 Cookie 查状态 -> authed=true",
      st == 200 and "true" in body.split("authed")[-1], body[:60])

# ============================================================
# 四、通过之后：创作闸门放开，浏览照旧
# ============================================================
print("-- 四、通过口令之后 --")

# 空主题会在建任务之前就被参数校验挡掉（400），
# 既能证明闸门放行了，又不会真启动一次视频生成
st, hd, body = req("POST", "/api/projects", body="topic=&file_ids=", cookie=cookie)
check("20 开始创作：能过闸门（400 参数校验，而非 401）", st == 400,
      f"HTTP {st} {body[:50]}")

st, hd, body = req("DELETE", f"/api/projects/{GHOST}", cookie=cookie)
check("21 删除：能过闸门（404 项目不存在，而非 401）", st == 404,
      f"HTTP {st} {body[:50]}")

st, hd, body = req("DELETE", "/api/projects/_uploads", cookie=cookie)
check("22 下划线开头的目录不可删（加固仍在）", st == 400, f"HTTP {st}")

st, hd, body = req("POST", "/api/settings/llm",
                   body="api_key=sk-evil", cookie=cookie)
check("23 改配置仍被 403 挡住（公网安全底线）", st == 403, f"HTTP {st}")

st, hd, _ = req("GET", "/", cookie=cookie)
check("24 通过后浏览照常", st == 200, f"HTTP {st}")

# ============================================================
# 五、伪造凭证与兼容性
# ============================================================
print("-- 五、伪造凭证 / 命令行兼容 --")

st, hd, _ = req("DELETE", f"/api/projects/{GHOST}", cookie="wk_pass=forged")
check("25 伪造 Cookie 对创作无效 -> 401", st == 401, f"HTTP {st}")

st, hd, _ = req("GET", "/", cookie="wk_pass=forged")
check("26 伪造 Cookie 不影响浏览（本来就不需要口令）", st == 200, f"HTTP {st}")

st, hd, _ = req("DELETE", f"/api/projects/{GHOST}", cookie="wk_pass=")
check("27 空 Cookie 对创作无效 -> 401", st == 401, f"HTTP {st}")

tok = base64.b64encode(f"demo:{PW}".encode()).decode()
st, hd, _ = req("DELETE", f"/api/projects/{GHOST}",
                headers={"Authorization": "Basic " + tok})
check("28 Basic 认证可用（curl -u 脚本不坏）-> 过闸门", st == 404, f"HTTP {st}")

bad = base64.b64encode(b"demo:wrong").decode()
st, hd, _ = req("DELETE", f"/api/projects/{GHOST}",
                headers={"Authorization": "Basic " + bad})
check("29 错误的 Basic 认证被拒 -> 401", st == 401, f"HTTP {st}")

st, hd, _ = req("GET", "/api/health")
check("30 健康检查不被 Basic 影响", st == 200, f"HTTP {st}")

# ============================================================
# 六、退出
# ============================================================
print("-- 六、退出 --")

st, hd, _ = req("GET", "/logout", cookie=cookie)
check("31 退出 -> 303 回登录页", st == 303 and hd.get("location") == "/login",
      f"HTTP {st}")
check("32 退出时清除 Cookie", "wk_pass=" in hd.get("set-cookie", ""))

# 令牌是由口令派生的（服务重启后 Cookie 不会失效），所以光删浏览器那个
# Cookie 不够 —— 服务端必须把这个令牌也作废，否则拿到过它的人还能接着用。
st, hd, _ = req("DELETE", f"/api/projects/{GHOST}", cookie=cookie)
check("33 退出后旧 Cookie 立即失效 -> 401", st == 401, f"HTTP {st}")

st, hd, body = req("GET", "/api/auth", cookie=cookie)
check("33b 退出后 /api/auth 报 authed=false", '"authed":false' in body, body[:60])

st, hd, _ = req("GET", "/", cookie=cookie)
check("33c 退出后仍能浏览（本来就不需要口令）", st == 200, f"HTTP {st}")

# 令牌是口令的确定函数，登出拉黑后如果不在登录时恢复，所有人都会被挡在门外。
# 这一项就是防这个回归的。
st, hd, body = req("POST", "/api/auth",
                   body="password=" + urllib.parse.quote(PW))
again = hd.get("set-cookie", "").split(";")[0]
check("33d 退出后重新登录仍可拿到会话",
      st == 200 and again.startswith("wk_pass="), f"HTTP {st}")

st, hd, _ = req("DELETE", f"/api/projects/{GHOST}", cookie=again)
check("33e 重新登录后新会话可用（过闸门 -> 404）", st == 404, f"HTTP {st}")

# ============================================================
# 七、限流（放最后：会锁住本机 IP）
# ============================================================
print("-- 七、防暴力破解 --")

locked_at = 0
for i in range(1, 16):
    st, hd, body = req("POST", "/api/auth", body="password=nope")
    if "次数过多" in body:
        locked_at = i
        break
check("34 连续错口令触发限流", 0 < locked_at <= 13, f"第 {locked_at} 次被锁")

st, hd, body = req("POST", "/api/auth",
                   body="password=" + urllib.parse.quote(PW))
check("35 锁定期间即使口令正确也拒绝", "次数过多" in body)

st, hd, _ = req("GET", "/")
check("36 限流不影响浏览", st == 200, f"HTTP {st}")

print("=" * 70)
ok = sum(1 for _, c, _ in results if c)
print(f"  通过 {ok}/{len(results)}")
if ok != len(results):
    print("  失败项：")
    for n, c, d in results:
        if not c:
            print(f"    - {n} {d}")
print("=" * 70)
sys.exit(0 if ok == len(results) else 1)
