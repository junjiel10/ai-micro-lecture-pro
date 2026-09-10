# -*- coding: utf-8 -*-
"""成片自动校验：把「肉眼才发现的问题」变成可重复执行的检查。

重点校验三件事（都是本项目真实踩过的坑）：
  1. 分辨率是否与所选画面比例一致
  2. 烧录字幕是否真的落在画面下部（曾因为 libass 坐标空间被放大到画面中部）
  3. 字幕条数 / 分镜数 / 音画时长是否自洽

用法：
    .venv\\Scripts\\python.exe tools\\verify_video.py                    # 校验全部项目
    .venv\\Scripts\\python.exe tools\\verify_video.py <项目号或目录名>
"""
from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np                                  # noqa: E402
from PIL import Image                               # noqa: E402

from agent import config, media                     # noqa: E402

OK, BAD, WARN = "✅", "❌", "⚠️ "


def frame_at(exe: str, video: str, t: float, out: str) -> bool:
    subprocess.run([exe, "-hide_banner", "-loglevel", "error", "-y", "-i", video,
                    "-ss", f"{t}", "-frames:v", "1", out], capture_output=True)
    return os.path.exists(out)


def gray(path: str) -> np.ndarray:
    return np.asarray(Image.open(path).convert("L"), dtype=np.int16)


def check_project(pdir: str) -> list[tuple[str, str]]:
    """返回 [(结论标记, 说明)]"""
    exe = media.ffmpeg_exe()
    meta: dict = {}
    mpath = os.path.join(pdir, "project.json")
    if os.path.exists(mpath):
        with open(mpath, encoding="utf-8") as f:
            meta = json.load(f)
    else:
        # 还在生成中，或只跑了脚本阶段 —— 退回读 plan.json
        ppath = os.path.join(pdir, "plan.json")
        if os.path.exists(ppath):
            with open(ppath, encoding="utf-8") as f:
                meta = json.load(f)
            meta["_partial"] = True

    res: list[tuple[str, str]] = []
    fmt = meta.get("fmt", "landscape")
    fspec = config.get_format(fmt)
    final = os.path.join(pdir, "final.mp4")
    nosub = os.path.join(pdir, "final_nosub.mp4")

    if meta.get("_partial") or not meta:
        res.append((WARN, "只有脚本阶段产物（成片尚未生成或生成被中断）"))

    if not os.path.exists(final):
        res.append((WARN, "还没有 final.mp4"))
        n_shots = len(meta.get("shots") or [])
        res.append((OK if n_shots else WARN, f"分镜 {n_shots} 个"))
        return res

    # ---- 1. 分辨率 ----
    # 临时帧一律写到系统临时目录：绝不能进 frames/，否则会混进分镜时间轴
    tmp = tempfile.mkdtemp(prefix="verify_")
    probe_png = os.path.join(tmp, "probe.png")
    if frame_at(exe, final, 1.0, probe_png):
        w, h = Image.open(probe_png).size
        good = (w, h) == (fspec["w"], fspec["h"])
        res.append((OK if good else BAD,
                    f"分辨率 {w}×{h}（期望 {fspec['w']}×{fspec['h']} · {fspec['name']}）"))

        # ---- 2. 字幕位置 ----
        if os.path.exists(nosub):
            shots = meta.get("shots") or []
            # 选一个旁白较长的分镜，保证那里一定有字幕
            mid = len(shots) // 2 if shots else 0
            t = sum(float(s.get("seconds") or 0) + config.SHOT_GAP
                    for s in shots[:mid]) + 2.0
            a_png = os.path.join(tmp, "sub.png")
            b_png = os.path.join(tmp, "nosub.png")
            if frame_at(exe, final, t, a_png) and frame_at(exe, nosub, t, b_png):
                diff = np.abs(gray(a_png) - gray(b_png))
                band = (diff > 60)
                ys = np.where(band.sum(axis=1) > 3)[0]
                if not len(ys):
                    res.append((WARN, f"t={t:.0f}s 处未检出字幕差异（该处可能刚好没字幕）"))
                else:
                    top_ratio = float(ys.min()) / h
                    bottom_gap = h - int(ys.max())
                    good = top_ratio > 0.55
                    res.append((OK if good else BAD,
                                f"字幕位于画面 {top_ratio * 100:.0f}% 以下"
                                f"（距底部 {bottom_gap}px）"))

    # ---- 3. 字幕与时长自洽 ----
    n_sub = 0
    srt = os.path.join(pdir, "narration.srt")
    if os.path.exists(srt):
        with open(srt, encoding="utf-8") as f:
            n_sub = f.read().count("-->")
    n_shots = len(meta.get("shots") or [])
    res.append((OK if n_sub >= n_shots > 0 else BAD,
                f"字幕 {n_sub} 条 / 分镜 {n_shots} 个"
                + ("，含 ASS 硬字幕源" if os.path.exists(
                    os.path.join(pdir, "narration.ass")) else "，⚠️ 缺 ASS")))

    real = media.probe_duration(final)
    expect = meta.get("duration")
    if expect:
        good = abs(real - float(expect)) < 1.5
        res.append((OK if good else BAD,
                    f"成片时长 {real:.1f}s（记录 {float(expect):.1f}s）"))

    score = (meta.get("review") or {}).get("score")
    res.append((OK, f"质检 {score} 分 · 插图 {'开' if meta.get('illustrations') else '关'}"
                    f" · {meta.get('source', '')}"))
    shutil.rmtree(tmp, ignore_errors=True)
    return res


def main() -> int:
    pattern = sys.argv[1] if len(sys.argv) > 1 else "*"
    dirs = sorted(d for d in glob.glob(os.path.join(config.OUTPUT_DIR, pattern))
                  if os.path.isdir(d) and not os.path.basename(d).startswith("_"))
    if not dirs:
        print("没有找到项目，请先生成一支成片。")
        return 1

    bad = 0
    for d in dirs:
        print("=" * 74)
        print(f"📼 {os.path.basename(d)}")
        for mark, text in check_project(d):
            print(f"   {mark} {text}")
            if mark == BAD:
                bad += 1
    print("=" * 74)
    print(f"共检查 {len(dirs)} 个项目，{'全部通过 🎉' if not bad else f'{bad} 项未通过 ❌'}")
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
