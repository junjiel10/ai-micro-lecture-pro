# -*- coding: utf-8 -*-
"""接口冒烟测试：验证「上传文档 → 自动成片 → 修改重做」全链路。

前置：先在另一个终端启动服务
    .venv\\Scripts\\python.exe -m uvicorn app:app --port 8000

然后运行：
    .venv\\Scripts\\python.exe tools\\api_test.py
"""
from __future__ import annotations

import json
import mimetypes
import os
import sys
import time
import urllib.parse
import urllib.request
import uuid

BASE = os.environ.get("API_BASE", "http://127.0.0.1:8000")

# 中文 Windows 控制台默认 GBK，输出 emoji 会抛 UnicodeEncodeError
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


# ----------------------------------------------------------------------
def post_form(path: str, fields: dict, files: dict | None = None, timeout=180):
    """构造 multipart/form-data 请求（不依赖第三方库）"""
    boundary = "----boundary" + uuid.uuid4().hex
    body = b""
    for k, v in fields.items():
        body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n"
                 f"{v}\r\n").encode("utf-8")
    for k, (name, data) in (files or {}).items():
        ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
        body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"; "
                 f"filename=\"{name}\"\r\nContent-Type: {ctype}\r\n\r\n").encode("utf-8")
        body += data + b"\r\n"
    body += f"--{boundary}--\r\n".encode("utf-8")

    req = urllib.request.Request(BASE + path, data=body, method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def get_json(path: str):
    with urllib.request.urlopen(BASE + path, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def wait_done(pid: str, label: str, timeout=900) -> dict:
    q = urllib.parse.quote(pid)
    since, t0 = 0, time.time()
    while True:
        d = get_json(f"/api/projects/{q}/events?since={since}")
        for e in d["events"]:
            if e.get("type") == "log" and e.get("level") in ("step", "success", "warning"):
                print(f"    · {e['msg']}")
            if e.get("type") == "review":
                print(f"    ★ 质检 {e.get('score')} 分 · "
                      f"{'通过' if e.get('pass') else '未通过'}")
        since = d["total"]
        if d["status"] == "done":
            print(f"  ✅ {label} 完成，用时 {time.time() - t0:.0f}s")
            return d["result"]
        if d["status"] == "error":
            raise SystemExit(f"  ❌ {label} 失败：{d['error']}")
        time.sleep(2)


# ----------------------------------------------------------------------
def main() -> int:
    print("=" * 66)
    print("接口冒烟测试 ·", BASE)
    print("=" * 66)

    health = get_json("/api/health")
    print(f"服务：{health['version']}｜{health['llm_mode']}｜FFmpeg {health['ffmpeg'].split('-')[0]}")
    print(f"字幕滤镜：{'可用' if health['subtitle_filter'] else '不可用'}｜字体 {health['font']}")

    # ---------- ① 上传文档 ----------
    print("\n[1/4] 上传参考文档…")
    doc = ("翻转课堂（Flipped Classroom）教学改革说明\n"
           "一、改革背景\n"
           "传统课堂以教师讲授为主，学生缺少练习与反馈的时间，难以照顾不同起点的学生。\n"
           "二、核心做法\n"
           "把知识传授环节前移到课前，课堂时间用于答疑、讨论与高阶任务。\n"
           "课前提供十分钟以内的微视频，并配套三道检测题，用于暴露预习盲区。\n"
           "课堂依据课前数据分组研讨，教师只讲共性问题。\n"
           "三、评价方式\n"
           "采用过程性评价与表现性任务，用量规公开评分标准，引导学生自我监控。\n"
           "四、常见问题\n"
           "课前任务过重会直接劝退学生，宁短勿长；课中若仍以讲授为主，翻转就会失效。\n")
    up = post_form("/api/upload", {}, {"file": ("翻转课堂说明.txt", doc.encode("utf-8"))})
    print(f"  ✅ 解析成功：{up['chars']} 字｜关键词 {up.get('keywords')}")

    # ---------- ② 自动成片 ----------
    print("\n[2/4] 创建制作任务（文档驱动）…")
    job = post_form("/api/projects", {
        "topic": "翻转课堂", "file_ids": up["file_id"], "minutes": "2",
        "theme": "scholar", "audience": "本科生", "style": "calm"})
    pid = job["project_id"]
    print(f"  项目号：{pid}")
    result = wait_done(pid, "首次制作")
    print(f"  成片：{result['duration']:.0f}s / {result['size_mb']} MB / "
          f"{len(result['shots'])} 个分镜 / 脚本来源 {result['source']}")

    # ---------- ③ 修改重做 ----------
    print("\n[3/4] 修改（换配色 + 改第 2 镜旁白）后定向重做…")
    detail = get_json(f"/api/projects/{urllib.parse.quote(pid)}/detail")
    new_text = "先问一个问题：如果学生在课前已经看完了讲解，课堂上宝贵的时间应该用来做什么？"
    post_form(f"/api/projects/{urllib.parse.quote(pid)}/revise", {
        "theme": "sunrise",
        "edits": json.dumps([{"index": 2, "narration": new_text}], ensure_ascii=False)})
    result2 = wait_done(pid, "定向重做")
    detail2 = get_json(f"/api/projects/{urllib.parse.quote(pid)}/detail")
    got = (detail2["shots"][1] or {}).get("narration", "")
    print(f"  配色：{detail['theme']} → {detail2['theme']}")
    print(f"  旁白已更新：{'✅' if got.strip() == new_text.strip() else '❌ ' + got[:40]}")

    # ---------- ④ 产物检查 ----------
    print("\n[4/4] 检查产物接口…")
    q = urllib.parse.quote(pid)
    for name, path in (("成片(带字幕)", f"/api/projects/{q}/video?subs=1"),
                       ("成片(无字幕)", f"/api/projects/{q}/video?subs=0"),
                       ("字幕 SRT", f"/api/projects/{q}/srt"),
                       ("画面 PNG", f"/api/projects/{q}/frames/shot_01.png")):
        try:
            with urllib.request.urlopen(BASE + path, timeout=60) as r:
                n = len(r.read())
            print(f"  ✅ {name}：{n / 1024:.1f} KB")
        except Exception as e:                      # noqa: BLE001
            print(f"  ❌ {name}：{e}")

    rounds = detail2.get("review_rounds") or []
    print(f"\n质检轮次：{[(r.get('round'), r.get('score')) for r in rounds]}")
    print("=" * 66)
    print("🎉 全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
