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
import hmac
import json
import os
import shutil
import threading
import time
import uuid

from fastapi import FastAPI, File, Form, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
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


# 可选访问口令：设了 ACCESS_PASSWORD 就启用 HTTP Basic 认证
# （浏览器会弹原生登录框，不需要额外做登录页）。留空 = 不开启。
ACCESS_USER = os.environ.get("ACCESS_USER", "demo")
ACCESS_PASSWORD = os.environ.get("ACCESS_PASSWORD", "")


@app.middleware("http")
async def _access_gate(request: Request, call_next):
    """公网部署的防盗用门禁：生成视频要烧 CPU 和大模型额度，别让人白用。

    /api/health 放行：它只有版本号、模型名、字体名这类信息，不含密钥，
    而云平台要靠它做健康检查（若被 401 挡住，容器会被判定为不健康而反复重启）。
    """
    if ACCESS_PASSWORD and request.url.path != "/api/health":
        ok = False
        auth = request.headers.get("authorization", "")
        if auth[:6].lower() == "basic ":
            try:
                raw = base64.b64decode(auth[6:]).decode("utf-8")
                user, _, pwd = raw.partition(":")
                ok = user == ACCESS_USER and hmac.compare_digest(pwd, ACCESS_PASSWORD)
            except Exception:
                ok = False
        if not ok:
            return Response(
                content="需要访问口令", status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="WonderKourse"'},
            )
    return await call_next(request)


@app.middleware("http")
async def _no_cache_static(request, call_next):
    """静态资源强制协商缓存：改了 css/js 刷新即生效，不会被浏览器内存缓存吃掉"""
    resp = await call_next(request)
    path = request.url.path
    if path.startswith("/static/") or path in ("/", "/guide", "/create"):
        resp.headers["Cache-Control"] = "no-cache, must-revalidate"
    return resp


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

ALLOWED_EXT = {".pdf", ".ppt", ".pptx", ".doc", ".docx", ".txt", ".md"}

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
    fid = uuid.uuid4().hex[:12]
    path = os.path.join(UPLOAD_DIR, f"{fid}{ext}")
    data = await file.read()
    if not data:
        return JSONResponse({"error": "文件为空"}, status_code=400)
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
    pdir = os.path.join(OUTPUT_DIR, os.path.basename(pid))
    if not os.path.isdir(pdir):
        return JSONResponse({"error": "项目不存在"}, status_code=404)
    shutil.rmtree(pdir, ignore_errors=True)
    with LOCK:
        TASKS.pop(pid, None)
    return {"ok": True}


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
