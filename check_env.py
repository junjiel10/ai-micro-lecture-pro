# -*- coding: utf-8 -*-
"""环境自检：一键确认「这台机器能不能跑通全流程」。

用法（在项目目录下）：
    .venv\\Scripts\\python.exe check_env.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent import config, media  # noqa: E402


def line(ok, title, detail=""):
    mark = "✅" if ok else ("⚠️ " if ok is None else "❌")
    print(f"{mark} {title}" + (f"  {detail}" if detail else ""))


def main() -> int:
    print("=" * 66)
    print("妙课生花 WonderKourse · 环境自检")
    print("=" * 66)
    print(f"项目目录：{config.BASE_DIR}")
    print(f"Python  ：{sys.version.split()[0]}  ({sys.executable})")
    print("-" * 66)

    problems = 0

    # 1) ffmpeg
    exe = media.ffmpeg_exe()
    if exe:
        line(True, "FFmpeg", f"{media.ffmpeg_version()}")
        print(f"         路径：{exe}")
    else:
        line(False, "FFmpeg", "未找到，请执行：pip install imageio-ffmpeg")
        problems += 1

    # 2) 字幕滤镜（libass）
    if exe:
        filters = media.available_filters()
        has_sub = "subtitles" in filters
        line(has_sub, "字幕烧录滤镜 (subtitles/libass)",
             "可用" if has_sub else "不可用，将自动改用 drawtext 方案")
        line("drawtext" in filters, "文字叠加滤镜 (drawtext)",
             "" if "drawtext" in filters else "不可用（不影响，字幕可用 libass）")

    # 3) 中文字体
    fp = config.font_path(False)
    line(bool(fp), "中文字体", fp or "未找到中文字体，画面文字可能变方块")

    # 4) TTS
    print("-" * 66)
    print("语音合成测试（这一步需要联网，约 3~10 秒）……")
    tmp = os.path.join(config.OUTPUT_DIR, "_selftest.mp3")
    res = media.synthesize("这是一段语音合成自检文本。", tmp)
    ok = res["engine"] != "silent" and res["duration"] > 0.5
    label = {"edge": "edge-tts 在线语音（音质最佳）",
             "sapi": "Windows 内置语音（离线）",
             "silent": "静音占位"}.get(res["engine"], res["engine"])
    line(ok, "语音合成引擎", f"{label}，时长 {res['duration']:.2f}s")
    if res["engine"] != "edge" and res.get("error"):
        print(f"         降级原因：{res['error'][:200]}")
    if res["engine"] == "silent":
        print("         提示：无网络也没有 SAPI 中文语音时，视频仍能生成（静音+字幕）")

    # 5) 大模型
    print("-" * 66)
    from agent import llm_client
    if llm_client.llm_available():
        line(True, "脚本生成方式", f"大模型：{config.LLM_MODEL}")
    else:
        line(None, "脚本生成方式",
             "内置教学脚本引擎（未配置 LLM_API_KEY，功能完整可用）")

    # 6) 画面能力
    print("-" * 66)
    fmts = " / ".join(f"{v['name']}（{v['w']}×{v['h']}）" for v in config.FORMATS.values())
    line(True, "画面比例", fmts)
    line(True, "结构化插图", "开启（概念图 / 流程链 / 标签云 / 对照板）"
         if config.ILLUSTRATIONS else "关闭（仅纯文字版式）")

    # 7) 文档解析依赖
    print("-" * 66)
    for mod, name in (("docx", "Word 解析 (python-docx)"),
                      ("pptx", "PPT 解析 (python-pptx)"),
                      ("pdfplumber", "PDF 解析 (pdfplumber)")):
        try:
            __import__(mod)
            line(True, name)
        except Exception:
            line(False, name, f"缺少 {mod}")
            problems += 1

    print("=" * 66)
    if problems == 0:
        print("结论：环境就绪，可以启动网站开始制作微课 ✅")
    else:
        print(f"结论：有 {problems} 项缺失，请先修复后再启动 ⚠️")
    return 0 if problems == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
