# -*- coding: utf-8 -*-
"""大模型客户端（可选）

· 配置了 LLM_API_KEY → 用大模型生成「教学内容字段」，再由 knowledge.assemble_from_fields
  装配成与无 Key 模式完全一致的分镜结构（保证下游 Agent 无需区分来源）。
· 未配置 Key        → 直接使用内置教学脚本引擎（knowledge.build_plan）。

兼容 OpenAI 风格接口：OpenAI / DeepSeek / 智谱 / 通义 / Kimi / 本地 Ollama 等，
只需在 .env 里改 LLM_BASE_URL 与 LLM_MODEL。
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

from . import config
from . import knowledge as KB
from .media import estimate_duration


def llm_available() -> bool:
    config.refresh()
    return bool(config.LLM_API_KEY)


def llm_label() -> str:
    if not llm_available():
        return "内置教学脚本引擎"
    return f"大模型（{config.LLM_MODEL}）"


# ----------------------------------------------------------------------
SYSTEM_PROMPT = """你是一位资深的教师教育专家与微课编导。请围绕用户给出的知识主题，
产出一套可直接录制的教学微课内容。要求：

1. 面向对象是高校学习者，语言口语化、适合朗读，避免书面腔与生僻词；
2. 内容必须有真实的学科信息量，不能空话套话，要给出概念、机制、案例与误区；
3. 严格输出 JSON，不要输出任何其他文字、不要使用 Markdown 代码块。

JSON 结构（所有字段都必须有内容）：
{
  "title": "视频标题（不超过 20 字）",
  "subject": "所属学科/领域，如：教育技术 · 教学设计",
  "hook": "开场引入，用一个问题或现象抓住注意力（60-90 字）",
  "definition": "核心概念的清晰界定，一句话说清它是什么（60-100 字）",
  "why": ["要点1|一句解释", "要点2|一句解释", "要点3|一句解释", "要点4|一句解释"],
  "core": ["核心要素1|一句解释", "核心要素2|一句解释", "核心要素3|一句解释", "核心要素4|一句解释"],
  "mechanism": [["环节名1", "一句说明"], ["环节名2", "一句说明"], ["环节名3", "一句说明"], ["环节名4", "一句说明"]],
  "applications": ["应用1|一句说明", "应用2|一句说明", "应用3|一句说明", "应用4|一句说明"],
  "cases": ["具体案例/场景，40-70 字", "具体案例/场景，40-70 字"],
  "myths": ["常见误区|正确认识", "常见误区|正确认识", "常见误区|正确认识", "常见误区|正确认识"],
  "tips": ["建议1|一句说明", "建议2|一句说明", "建议3|一句说明", "建议4|一句说明"],
  "summary": ["要点回顾1", "要点回顾2", "要点回顾3", "要点回顾4"],
  "ending": "结尾升华，一句有力量的话（40-70 字）"
}

注意：why/core/applications/myths/tips 每条都必须是「短标题|一句解释」的格式，
短标题不超过 10 个字；mechanism 用两元素数组。"""


def _chat(messages, max_tokens: int = 2600, temperature: float = 0.75,
          timeout: int = 120) -> str:
    body = json.dumps({
        "model": config.LLM_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }, ensure_ascii=False).encode("utf-8")

    url = config.LLM_BASE_URL.rstrip("/")
    if not url.endswith("/chat/completions"):
        url += "/chat/completions"

    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", "Bearer " + config.LLM_API_KEY)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"大模型接口返回 {e.code}：{detail}")
    except Exception as e:
        raise RuntimeError(f"大模型调用失败：{e}")
    return data["choices"][0]["message"]["content"].strip()


def _parse_json(text: str) -> dict:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("模型输出中未找到 JSON")
    return json.loads(text[start:end + 1])


def generate_fields(topic: str, source_text: str = "", audience: str = "本科生",
                    minutes: float = 4.0) -> dict:
    """让大模型产出教学内容字段"""
    user = f"知识主题：{topic}\n面向对象：{audience}\n目标时长：约 {minutes:.0f} 分钟\n"
    if source_text:
        user += f"\n以下是教师提供的参考文档内容，请优先依据它来组织讲解：\n{source_text[:6000]}\n"
    user += "\n请输出 JSON："
    raw = _chat([
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ])
    fields = _parse_json(raw)
    # 归一化 mechanism（可能是 list[list] 或 list[str]）
    mech = []
    for m in fields.get("mechanism", []) or []:
        if isinstance(m, (list, tuple)) and len(m) >= 2:
            mech.append((str(m[0]), str(m[1])))
        elif isinstance(m, str):
            a, _, b = m.partition("|")
            mech.append((a.strip(), b.strip()))
    fields["mechanism"] = mech
    return fields


def generate_plan(topic: str, source_text: str = "", audience: str = "本科生",
                  minutes: float = 4.0, style: str = "calm") -> tuple[dict, str]:
    """返回 (plan, 备注)。大模型失败时自动降级到内置引擎，保证流程不中断。"""
    if llm_available():
        try:
            fields = generate_fields(topic, source_text, audience, minutes)
            plan = KB.assemble_from_fields(
                topic, fields, audience=audience, minutes=minutes, style=style,
                source=f"大模型生成（{config.LLM_MODEL}）")
            return plan, ""
        except Exception as e:
            plan = KB.build_plan(topic, source_text, audience, minutes, style)
            return plan, f"大模型调用失败，已自动降级内置引擎：{str(e)[:180]}"

    plan = KB.build_plan(topic, source_text, audience, minutes, style)
    return plan, ""


# ----------------------------------------------------------------------
# ③ 脚本层：为已确定的分镜骨架撰写旁白稿
# ----------------------------------------------------------------------
NARRATION_PROMPT = """你是一位教师教育领域的微课编导。下面已经确定了微课的分镜结构，
请你为每一个分镜撰写旁白稿。要求：

1. 旁白要口语化、适合语音合成朗读，避免书面语与生僻词；
2. **每个分镜的旁白字数必须落在用户消息给出的区间内**：这是硬性要求，
   全片总时长完全由它决定。宁可信息精练，也不要写超。
   片头与片尾可以取区间下限，中间讲内容的镜头取中上限；
3. 每个分镜都要写满信息量：讲清楚「是什么 / 为什么 / 怎么做」中的一两个点，不要空话；
4. 全片旁白要连贯成篇：上一镜结尾自然引出下一镜，不要出现「上一页」「如图所示」这类词；
5. 首镜是片头（自然开场并点题），末镜是片尾（简短有力收尾）；
6. 严格输出 JSON，不要输出任何其他文字或 Markdown 代码块。

输出格式：{"narrations": [{"index": 1, "narration": "……"}, {"index": 2, "narration": "……"}]}"""


def write_narration(topic: str, shots: list[dict], source_text: str = "",
                    audience: str = "本科生",
                    budget: tuple[int, int] | None = None,
                    target_sec: float | None = None) -> list[dict]:
    """让大模型为分镜骨架写旁白，返回新的 shots 列表（失败抛异常，由调用方降级）"""
    skeleton = [{"index": s.get("index"), "scene": s.get("scene"),
                 "title": s.get("title"), "bullets": s.get("bullets", [])}
                for s in shots]
    user = (f"知识主题：{topic}\n面向对象：{audience}\n"
            f"分镜结构：{json.dumps(skeleton, ensure_ascii=False)}\n")
    if budget:
        lo, hi = budget
        user += (f"\n【硬性要求】每个分镜的旁白控制在 {lo}~{hi} 字之间。"
                 f"全片共 {len(shots)} 个分镜，按此字数正好是目标时长，"
                 f"请务必不要在某个分镜上写超。\n")
    if source_text:
        user += f"\n参考文档内容（请依据它组织讲解）：\n{source_text[:5000]}\n"
    user += "\n请输出 JSON："
    raw = _chat([
        {"role": "system", "content": NARRATION_PROMPT},
        {"role": "user", "content": user},
    ], max_tokens=3000)
    data = _parse_json(raw)
    items = data.get("narrations") or data.get("shots") or []
    by_index = {}
    for it in items:
        if isinstance(it, dict) and it.get("index") is not None:
            by_index[int(it["index"])] = str(it.get("narration", "")).strip()

    out = []
    for s in shots:
        shot = dict(s)
        text = by_index.get(shot.get("index"), "")
        shot["narration"] = text or shot.get("narration") or shot.get("title", "")
        out.append(shot)

    # 第二遍：大模型对「目标时长偏长」的镜头往往写得不够满，
    # 只把偏短的镜头拿回去补写，避免重写全片浪费 token、也避免改动已经合适的镜头。
    if budget and target_sec:
        total = sum(estimate_duration(s["narration"]) for s in out)
        if total < target_sec * 0.88:
            out = _expand_short(topic, out, budget, audience) or out
    return out


def _expand_short(topic: str, shots: list[dict], budget: tuple[int, int],
                  audience: str) -> list[dict] | None:
    """把字数明显不够的镜头送回大模型扩写，其余镜头原样保留。"""
    lo, hi = budget
    short = [s for s in shots
             if len(re.sub(r"\s", "", s.get("narration") or "")) < lo * 0.9]
    if not short:
        return None
    payload = [{"index": s["index"], "scene": s.get("scene"),
                "title": s.get("title"), "bullets": s.get("bullets", []),
                "narration": s["narration"]} for s in short]
    prompt = (
        f"知识主题：{topic}\n面向对象：{audience}\n\n"
        f"下面是已写好的旁白，但有几镜字数偏少，导致全片比目标时长短。\n"
        f"请把每一镜的旁白扩写到 {lo}~{hi} 字：保持原有观点不变，"
        f"补上具体的解释、例子或作用说明，不要重复同一句话。\n"
        f"只输出这几镜，不要改动其他镜头。\n\n"
        f"待扩写镜头：{json.dumps(payload, ensure_ascii=False)}\n\n请输出 JSON："
    )
    try:
        data = _parse_json(_chat([
            {"role": "system", "content": NARRATION_PROMPT},
            {"role": "user", "content": prompt},
        ], max_tokens=3000))
    except Exception:                                   # noqa: BLE001
        return None                                     # 补写失败就按原样用，不阻塞流程

    fixed = {}
    for it in (data.get("narrations") or data.get("shots") or []):
        if isinstance(it, dict) and it.get("index") is not None:
            text = str(it.get("narration", "")).strip()
            if text:
                fixed[int(it["index"])] = text
    for s in shots:
        text = fixed.get(s["index"])
        if text and len(re.sub(r"\s", "", text)) > len(re.sub(r"\s", "", s["narration"])):
            s["narration"] = text
    return shots
