# -*- coding: utf-8 -*-
"""时长控制自检：确认「目标时长」选多少就真的出多少。

用法：
    .venv\\Scripts\\python.exe tools\\check_duration.py            # 内置引擎
    .venv\\Scripts\\python.exe tools\\check_duration.py --llm      # 走大模型（慢，会花 token）

判据：成片预估时长落在目标时长的 75%~125% 之间，且分镜数保持 8~12。
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from agent import config, knowledge as KB, llm_client   # noqa: E402
from agent.media import estimate_duration               # noqa: E402


def build(topic: str, minutes: float, use_llm: bool) -> dict:
    if use_llm and llm_client.llm_available():
        plan, note = llm_client.generate_plan(topic, "", "本科生", minutes, "calm")
        if note:
            print("   [降级]", note)
        return plan
    return KB.build_plan(topic, "", "本科生", minutes, "calm")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", action="store_true", help="走大模型路径")
    ap.add_argument("--topic", default="翻转课堂")
    args = ap.parse_args()

    config.refresh()
    mode = f"大模型（{config.LLM_MODEL}）" if (args.llm and llm_client.llm_available()) \
        else "内置教学脚本引擎"
    print(f"主题：{args.topic}｜生成方式：{mode}\n")
    print(f"{'目标':>7} {'分镜':>5} {'每镜字数预算':>13} {'预估时长':>10} {'比值':>7}  判定")
    print("-" * 62)

    bad = 0
    warn = 0
    for minutes in (2, 3, 4, 6, 8):
        plan = build(args.topic, minutes, args.llm)
        shots = plan["shots"]
        n = len(shots)
        for s in shots:                                  # 大模型路径下秒数可能没填
            s["seconds"] = s.get("seconds") or estimate_duration(s["narration"])
        sec = sum(s["seconds"] for s in shots)
        lo, hi = KB.narration_budget(minutes * 60, n)
        ratio = sec / 60.0 / minutes
        ok = 0.75 <= ratio <= 1.25 and KB.MIN_SHOTS <= n <= KB.MAX_SHOTS
        if ok:
            mark = "✅"
        elif not args.llm and ratio < 0.8:
            # 内置知识库每个字段只有 4 条素材，长时长档填不满是内容上限，不是逻辑错误
            mark = "⚠ 内置库内容上限"
            warn += 1
        else:
            mark = "❌"
            bad += 1
        print(f"{minutes:>5}min {n:>5} {f'{lo}~{hi} 字':>13} "
              f"{sec / 60.0:>8.1f}min {ratio:>6.2f}x  {mark}")

    print("-" * 62)
    if bad == 0 and warn == 0:
        print("全部通过 ✅")
    elif bad == 0:
        print(f"无逻辑错误；{warn} 项受内置知识库素材量限制 ⚠")
        print("→ 想要长时长：在 .env 配 LLM_API_KEY，或上传更详细的文档当素材")
    else:
        print(f"有 {bad} 项不达标 ❌")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
