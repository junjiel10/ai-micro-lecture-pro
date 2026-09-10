# -*- coding: utf-8 -*-
"""版式预览：一次性把全部版式（含插图）渲染成图片，用于快速检查画面效果。

不需要跑完整视频流程，几秒钟就能出图。

用法：
    .venv\\Scripts\\python.exe tools\\preview_frames.py
    .venv\\Scripts\\python.exe tools\\preview_frames.py --fmt portrait --theme scholar
输出：
    output/_preview/<fmt>/<layout>.png
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import config, slides  # noqa: E402
from agent.agents import VisualAgent  # noqa: E402

DEMO_SHOTS = [
    {"layout": "cover", "scene": "封面", "title": "翻转课堂：把课堂时间还给高阶思维",
     "bullets": [], "subtitle": "", "meta": "面向本科生", "visual_kind": "motif",
     "narration": "大家好，这节课我们来聊一个话题：翻转课堂。我会用大约四分钟，把它讲清楚、讲透。"},
    {"layout": "quote", "scene": "问题引入", "title": "先从一个问题说起", "visual_kind": "motif",
     "bullets": ["如果学生在课前已经看完了讲解，那课堂上宝贵的时间应该用来做什么？"],
     "narration": "如果学生在课前已经看完了讲解，那课堂上宝贵的时间应该用来做什么？"},
    {"layout": "points", "scene": "为什么重要", "title": "为什么值得关注",
     "bullets": ["课堂时间稀缺|讲解占满课堂，学生缺少练习与反馈的机会",
                 "差异难以照顾|统一讲授对快慢学生同时不友好",
                 "技术条件成熟|微课与在线平台让课前学习成为可能",
                 "提升参与度|课堂转向任务与讨论，学生投入度更高"],
     "narration": ""},
    {"layout": "board", "scene": "核心要素", "title": "拆开来看，它由这几部分组成",
     "visual_kind": "concept",
     "bullets": ["课前|完成基础认知，配检测题暴露盲区",
                 "课中|聚焦疑难与迁移应用，教师做诊断",
                 "课后|以项目或拓展任务巩固学习",
                 "评价|过程性数据支撑个性化反馈"],
     "narration": ""},
    {"layout": "board", "scene": "运作机制", "title": "它是怎么运转起来的",
     "visual_kind": "flow",
     "bullets": ["分析|明确学习需要与学习者特征",
                 "设计|把目标拆成可观测的行为动词",
                 "开发|准备内容、活动、资源与评价工具",
                 "实施|组织学习并收集过程性证据",
                 "评价|依据证据判断达成度并反哺设计"],
     "narration": ""},
    {"layout": "steps", "scene": "实践建议", "title": "给你的几条可操作建议",
     "bullets": ["课前任务要轻|过长会劝退学生，宁短勿长并配检测",
                 "课堂必须有变|如果课中仍以讲授为主，翻转就失效了",
                 "评价要跟上|过程性数据是翻转能否持续的关键",
                 "先小范围试点|选一个班或一个单元试，降低改革风险"],
     "narration": ""},
    {"layout": "compare", "scene": "常见误区", "title": "这些误解需要澄清",
     "visual_kind": "compare",
     "bullets": ["内容讲完就算完成教学|学生学会才算完成",
                 "活动越多课堂越丰富|活动要服务于目标",
                 "评价就是期末考试|评价应贯穿过程",
                 "改革就是推翻重来|改革是渐进优化"],
     "narration": ""},
    {"layout": "board", "scene": "应用场景", "title": "在实践中怎么用",
     "visual_kind": "tags",
     "bullets": ["课前自学|短微课加检测题", "课中研讨|基于数据分组讨论",
                 "课后拓展|真实项目任务", "学情诊断|用平台数据定位薄弱点"],
     "narration": ""},
    {"layout": "summary", "scene": "要点回顾", "title": "这节课我们讲了什么",
     "bullets": ["翻转的本质是重新分配课堂时间", "课前解决认知，课中解决思维与迁移",
                 "没有评价配套，翻转很难持续", "先试点、再推广是稳妥路径"],
     "narration": ""},
    {"layout": "ending", "scene": "片尾", "title": "谢谢观看", "visual_kind": "motif",
     "bullets": ["翻转的本质是重新分配课堂时间", "课前解决认知，课中解决思维与迁移",
                 "没有评价配套，翻转很难持续"],
     "narration": ""},
]


def make_art(renderer: slides.SlideRenderer, shot: dict):
    """直接复用 VisualAgent 的插图决策，保证「预览 == 成片」"""
    return VisualAgent()._make_art(renderer, shot)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fmt", default="landscape", choices=list(config.FORMATS))
    ap.add_argument("--theme", default="deepsea", choices=list(config.THEMES))
    args = ap.parse_args()

    out_dir = os.path.join(config.OUTPUT_DIR, "_preview", args.fmt)
    os.makedirs(out_dir, exist_ok=True)
    renderer = slides.SlideRenderer(fmt=args.fmt, theme_name=args.theme,
                                    subject="教学模式改革")
    total = len(DEMO_SHOTS)
    for i, shot in enumerate(DEMO_SHOTS, 1):
        shot = dict(shot)
        shot.setdefault("index", i)
        art = make_art(renderer, shot)
        out = os.path.join(out_dir, f"{i:02d}-{shot['layout']}.png")
        renderer.render_shot(shot, i, total, out, art)
        print(f"  ✅ {os.path.basename(out)}"
              + (f"  （插图 {shot['visual_kind']}）" if art is not None else ""))
    print(f"\n输出目录：{out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
