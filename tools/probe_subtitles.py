# -*- coding: utf-8 -*-
"""诊断脚本：找出「本机 ffmpeg 烧录中文字幕」的正确姿势。

不同 ffmpeg 构建对 libass / fontconfig 的支持差异很大，本脚本会依次尝试
多种字幕滤镜写法，各自输出一帧 PNG，你只要打开图片看中文是否正常即可。

用法：
    .venv\\Scripts\\python.exe tools\\probe_subtitles.py
输出：
    output/_probe/candidate_1.png / candidate_2.png ...
    output/_probe/result.txt
"""
from __future__ import annotations

import glob
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import config, media  # noqa: E402

TEXT = "翻转课堂：把课堂时间还给高阶思维 ABC 123"
STYLE = ("FontName={font},FontSize=16,PrimaryColour=&H00FFFFFF,"
         "OutlineColour=&HFF1A2B4A,BorderStyle=1,Outline=2,Shadow=0,"
         "Alignment=2,MarginV=24")


def build_srt(path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"1\n00:00:00,000 --> 00:00:02,000\n{TEXT}\n\n")


def variants(out_dir: str, font_file: str) -> list[tuple[str, str | None]]:
    """返回 [(说明, vf 字符串)]；vf 为 None 表示使用 drawtext 方案"""
    fonts_dir = os.path.join(out_dir, "fonts")
    os.makedirs(fonts_dir, exist_ok=True)
    local_font = os.path.join(fonts_dir, os.path.basename(font_file))
    if not os.path.exists(local_font):
        shutil.copy2(font_file, local_font)

    return [
        ("① 默认字体（不指定 FontName）", "subtitles=probe.srt"),
        ("② 只指定 FontName=Microsoft YaHei",
         "subtitles=probe.srt:force_style='" + STYLE.format(font="Microsoft YaHei") + "'"),
        ("③ 自带字体目录 + FontName=Microsoft YaHei",
         "subtitles=probe.srt:fontsdir=fonts:force_style='"
         + STYLE.format(font="Microsoft YaHei") + "'"),
        ("④ 自带字体目录 + FontName=MSYH",
         "subtitles=probe.srt:fontsdir=fonts:force_style='"
         + STYLE.format(font="MSYH") + "'"),
        ("⑤ drawtext 指定 fontfile（不依赖 libass 字体查找）", None),
    ]


def run_variant(exe: str, out_dir: str, vf: str | None, n: int) -> tuple[bool, str]:
    mp4 = f"candidate_{n}.mp4"
    if vf is None:
        txt_file = "line.txt"
        with open(os.path.join(out_dir, txt_file), "w", encoding="utf-8") as f:
            f.write(TEXT)
        font = config.font_path(True).replace("\\", "/").replace(":", "\\:")
        vf = (f"drawtext=fontfile='{font}':textfile={txt_file}:"
              f"fontsize=18:fontcolor=white:borderw=2:bordercolor=0x1A2B4A:"
              f"x=(w-text_w)/2:y=h-th-24")
    cmd = [exe, "-hide_banner", "-loglevel", "error", "-y",
           "-loop", "1", "-i", "src.png", "-t", "2",
           "-vf", vf, "-c:v", "libx264", "-pix_fmt", "yuv420p", mp4]
    proc = subprocess.run(cmd, cwd=out_dir, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        err = (proc.stderr or "").strip().splitlines()
        return False, (err[-1] if err else "未知错误")[:160]

    png = f"candidate_{n}.png"
    subprocess.run([exe, "-hide_banner", "-loglevel", "error", "-y",
                    "-ss", "0.8", "-i", mp4, "-frames:v", "1", png],
                   cwd=out_dir, capture_output=True)
    ok = os.path.exists(os.path.join(out_dir, png))
    return ok, "" if ok else "抽帧失败"


def main() -> int:
    out_dir = os.path.join(config.OUTPUT_DIR, "_probe")
    os.makedirs(out_dir, exist_ok=True)
    from PIL import Image
    Image.new("RGB", (640, 360), (24, 40, 70)).save(os.path.join(out_dir, "src.png"))
    build_srt(os.path.join(out_dir, "probe.srt"))

    exe = media.ffmpeg_exe()
    font_file = config.font_path(False)
    print(f"ffmpeg : {exe}")
    print(f"字幕滤镜: {'可用' if media.has_filter('subtitles') else '不可用'}")
    print(f"中文字体: {font_file}\n")

    lines = []
    for n, (name, vf) in enumerate(variants(out_dir, font_file), 1):
        ok, err = run_variant(exe, out_dir, vf, n)
        status = "生成成功" if ok else f"失败 → {err}"
        print(f"{name}\n    {status}")
        lines.append(f"方案{n} {name}\n  结果: {status}\n")
        if not ok:
            for f in glob.glob(os.path.join(out_dir, f"candidate_{n}.*")):
                try:
                    os.remove(f)
                except OSError:
                    pass

    with open(os.path.join(out_dir, "result.txt"), "w", encoding="utf-8") as f:
        f.write(f"测试字幕：{TEXT}\n\n" + "\n".join(lines))

    print(f"\n图片目录：{out_dir}")
    print("请打开 candidate_*.png，看哪一个中文显示正常（不是方块/乱码）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
