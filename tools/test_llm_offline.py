# -*- coding: utf-8 -*-
"""离线验证大模型通路（不需要真的 API Key，也不联网）。

做法：在本机起一个假的「OpenAI 兼容」接口（模拟 DeepSeek 的
/v1/chat/completions），然后让 ScriptAgent / StructureAgent 走大模型路径，
验证：请求组装 → 返回解析 → JSON 提取 → 分镜装配 这条链路真的通。

用法：
    .venv\\Scripts\\python.exe tools\\test_llm_offline.py
"""
from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PORT = 18080
BASE = f"http://127.0.0.1:{PORT}/v1"

# 假模型返回的内容（故意带上 ```json 围栏和前后废话，检验解析健壮性）
FIELDS_JSON = {
    "title": "翻转课堂的三重门",
    "subject": "教学模式改革",
    "hook": "同样一节课，为什么有的班级讨论得热火朝天，有的班级却没人抬头？差别可能不在学生，而在于课前那十分钟。",
    "definition": "翻转课堂是把知识传授前移到课前、把课堂时间留给答疑与高阶任务的教学模式，本质是重新分配课堂时间与认知负荷。",
    "why": ["课堂时间稀缺|讲解占满课堂，学生没有练习与纠错的机会",
            "差异难以照顾|统一讲授对快慢学生同时不友好",
            "技术条件成熟|微课平台让课前自学成为可行选择",
            "参与度更高|课堂转向任务与讨论，学生必须开口"],
    "core": ["课前任务|短小精悍，配检测题暴露盲区",
             "课中活动|聚焦疑难与迁移，教师做诊断",
             "课后巩固|以真实任务完成学习闭环",
             "评价反馈|过程性数据支撑个性化指导"],
    "mechanism": [["分析", "明确目标与学情起点"], ["设计", "把目标拆成可观测行为"],
                  ["开发", "准备微课与检测工具"], ["实施", "组织课堂研讨与反馈"]],
    "applications": ["课前自学|十分钟微课加三道检测题",
                     "课中研讨|依据预习数据分组讨论",
                     "课后拓展|真实情境任务驱动迁移",
                     "学情诊断|用平台数据定位薄弱点"],
    "cases": ["某课程把讲解录成十分钟微课，课堂改为小组研讨，提问人数明显增加。",
              "教师依据课前检测数据，只讲共性问题，课堂效率明显提升。"],
    "myths": ["翻转就是看视频|关键在课堂活动是否真的发生",
              "课前任务越多越好|任务过重会直接劝退学生",
              "所有内容都适合翻转|事实性知识更适合前置"],
    "tips": ["任务要轻|宁短勿长并配检测题", "课堂要变|课中不能还是讲授",
             "评价要跟上|过程性数据是关键"],
    "summary": ["翻转的本质是重新分配课堂时间", "课前解决认知，课中解决思维与迁移",
                "没有评价配套，翻转很难持续"],
    "ending": "真正需要翻转的不是视频和课堂，而是我们对课堂时间价值的判断。",
}

NARRATION_JSON = {
    "narrations": [
        {"index": i, "narration": f"【大模型撰写】这是第 {i} 个分镜的旁白稿，"
                                  f"用于验证大模型通路是否真的打通，长度足够。"
                                  f"实际使用时会替换为针对该分镜的真实讲解内容。"}
        for i in range(1, 20)
    ]
}


class Handler(BaseHTTPRequestHandler):
    received: list = []

    def log_message(self, *a):        # 静音
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n).decode("utf-8"))
        Handler.received.append(body)
        system = body["messages"][0]["content"]

        if "JSON" in system and "hook" in system:          # 内容字段请求
            payload = "好的，以下是结果：\n```json\n" + json.dumps(
                FIELDS_JSON, ensure_ascii=False) + "\n```"
        else:                                              # 旁白请求
            payload = json.dumps(NARRATION_JSON, ensure_ascii=False)

        data = json.dumps({
            "id": "chatcmpl-test", "object": "chat.completion",
            "model": body.get("model", "test"),
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": payload}}],
        }, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main() -> int:
    srv = HTTPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    os.environ["LLM_API_KEY"] = "sk-test-offline"
    os.environ["LLM_BASE_URL"] = BASE
    os.environ["LLM_MODEL"] = "test-model"

    from agent import config, llm_client
    config.refresh()
    from agent.agents import StructureAgent, ScriptAgent

    print("=" * 70)
    print(f"假接口已启动：{BASE}    脚本来源：{llm_client.llm_label()}")
    print("=" * 70)

    logs: list[str] = []

    def log(level, msg):
        logs.append(f"[{level}] {msg}")
        print(f"  [{level}] {msg}")

    topic = "翻转课堂"
    fields, structure, source = StructureAgent().blueprint(
        topic, "", log, audience="本科生", minutes=3)
    print(f"\n  内容来源：{source}")
    print(f"  结构：{len(structure['shots'])} 个分镜，"
          f"版式 {' → '.join(s['layout'] for s in structure['shots'])}")

    plan = ScriptAgent().write(topic, fields, structure, "", log,
                               audience="本科生", minutes=3, source=source)
    print(f"\n  最终来源：{plan['source']}")
    print(f"  旁白总长：{len(plan['script'])} 字，预估 {plan['minutes']} 分钟")
    for s in plan["shots"][:3]:
        print(f"    [{s['index']:02d}] {s['scene']}: {s['narration'][:60]}")

    # ---------------------------- 断言 ----------------------------
    ok = True
    print("\n" + "-" * 70)
    n_fields = sum(1 for b in Handler.received
                   if "hook" in b["messages"][0]["content"])
    n_narr = len(Handler.received) - n_fields
    print(f"  接口调用：内容字段请求 {n_fields} 次，旁白请求 {n_narr} 次")

    checks = [
        ("大模型可用", llm_client.llm_available()),
        ("两次接口调用都发生", n_fields >= 1 and n_narr >= 1),
        ("内容来自大模型", "大模型" in plan["source"]),
        ("标题取自大模型返回", plan["title"] == FIELDS_JSON["title"]),
        ("分镜数在 8~12 之间", 8 <= len(plan["shots"]) <= 12),
        ("旁白由大模型撰写", all("大模型撰写" in s["narration"] for s in plan["shots"])),
        ("核心要素进入分镜", any(s["scene"] == "核心要素" for s in plan["shots"])),
        ("图文混排版式已分配", any(s["layout"] == "board" for s in plan["shots"])),
    ]
    for name, good in checks:
        print(f"  {'✅' if good else '❌'} {name}")
        ok = ok and good

    srv.shutdown()
    print("=" * 70)
    print("🎉 大模型通路验证通过" if ok else "❌ 存在未通过项，请检查")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
