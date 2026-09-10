# -*- coding: utf-8 -*-
"""命令行出片工具：不打开网页也能跑完整流程（用于自检与批量制作）。

用法：
    .venv\\Scripts\\python.exe tools\\make_video.py "翻转课堂" --minutes 3
    .venv\\Scripts\\python.exe tools\\make_video.py "课程思政" --file D:\\讲义.pdf --theme scholar
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import config  # noqa: E402
from agent.orchestrator import Orchestrator  # noqa: E402

ICON = {"思考": "🤔", "行动": "🔧", "观察": "👀", "step": "▶", "info": "·",
        "warning": "⚠️", "success": "✅"}


def printer(e: dict) -> None:
    t = e.get("type")
    if t == "log":
        print(f"  {ICON.get(e['level'], '·')} [{e.get('agent') or '-'}] {e['msg']}")
    elif t == "step":
        print(f"\n{'=' * 70}\n第 {e['index']}/{e['total']} 步 · {e['label']}"
              + (f"（{e['note']}）" if e.get("note") else "") + f"\n{'=' * 70}")
    elif t == "agent":
        print(f"  ⟶ Agent[{e['agent']}] {e['status']}"
              + (f" — {e['detail']}" if e.get("detail") else ""))
    elif t == "review":
        print(f"  ★ 质检 r{e.get('round')}：{'通过' if e['pass'] else '未通过'}，"
              f"得分 {e.get('score')}")
        for c in e.get("checks", []):
            print(f"      {'✔' if c['ok'] else '✘'} {c['name']}：{c['detail']}")
    elif t == "rework":
        print(f"  ↻ 定向重做：{e['what']}")
    elif t == "result":
        d = e["data"]
        print(f"\n{'=' * 70}")
        print(f"🎬 成片：{d['title']}")
        print(f"   分镜 {len(d['shots'])} 个 · 时长 {d['duration']:.0f}s · "
              f"{d.get('resolution', '')} · {d['size_mb']} MB · 质检 {d['review']['score']} 分")
        print(f"   脚本来源：{d['source']}")
        print(f"   文件位置：{os.path.join(config.OUTPUT_DIR, d['project_id'])}")
        print(f"{'=' * 70}")


def main() -> int:
    ap = argparse.ArgumentParser(description="妙课生花 WonderKourse · 命令行出片")
    ap.add_argument("topic", help="知识主题")
    ap.add_argument("--file", action="append", default=[], help="参考文档（可多次）")
    ap.add_argument("--minutes", type=float, default=4.0, help="目标时长（分钟）")
    ap.add_argument("--theme", default="deepsea",
                    choices=["deepsea", "scholar", "sunrise"], help="画面配色")
    ap.add_argument("--fmt", default="landscape", choices=["landscape", "portrait"],
                    help="画面比例：横版 16:9 / 竖版 9:16")
    ap.add_argument("--no-illustrations", action="store_true",
                    help="关闭自动插图，只用纯文字版式")
    ap.add_argument("--style", default="calm",
                    choices=["calm", "bright", "warm"], help="背景音乐风格")
    ap.add_argument("--audience", default="本科生", help="面向对象")
    args = ap.parse_args()

    files = []
    for p in args.file:
        if not os.path.exists(p):
            print(f"❌ 文件不存在：{p}")
            return 2
        files.append({"path": os.path.abspath(p), "name": os.path.basename(p)})

    print(f"主题：{args.topic}｜目标 {args.minutes:.0f} 分钟｜{args.fmt}｜"
          f"配色 {args.theme}｜插图 {'开' if not args.no_illustrations else '关'}｜"
          f"参考文档 {len(files)} 份")
    orch = Orchestrator()
    try:
        orch.run(args.topic, files=files, audience=args.audience,
                 minutes=args.minutes, style=args.style, theme=args.theme,
                 fmt=args.fmt, illustrations=not args.no_illustrations,
                 emit=printer)
    except KeyboardInterrupt:
        print("\n已中止")
        return 130
    except Exception as e:
        print(f"\n❌ 制作失败：{e}")
        import traceback
        traceback.print_exc()
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
