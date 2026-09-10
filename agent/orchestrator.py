# -*- coding: utf-8 -*-
"""Orchestrator 主控 —— 对应设计图的「编排层」

Plan 模式：固定工作流 + Agent 自主决策。
    ① 文档解析 → ② 知识结构化 → ③ 分镜脚本 → ④ 配音配乐
    → ⑤ 画面生成 → ⑥ 剪辑合成 → ⑦ 质检打分
                                 └── 不合格 → 定向回退重做（V1 → V2）

设计要点：
· 每一步职责单一、产出落盘，失败可断点重试；
· 通过 emit(event) 向外部（Web 前端）实时广播结构化事件：
     {"type":"step"}  当前进行到第几步 / 共几步
     {"type":"agent"} 某个 Agent 的运行状态（running/done/retry/failed/skip）
     {"type":"log"}   思考 / 行动 / 观察 日志
     {"type":"review"} 质检结果（含得分与逐项检查）
     {"type":"result"} 最终产物
· 质检回退是「定向修复」而不是整条重跑：只重做被判不合格的环节。
"""
from __future__ import annotations

import json
import os
import re
import time

from . import agents as AG
from . import config
from . import llm_client

STEP_TOTAL = 7


class Canceled(Exception):
    """用户主动中止"""


class Orchestrator:
    def __init__(self):
        self.document = AG.DocumentParserAgent()
        self.structure = AG.StructureAgent()
        self.script = AG.ScriptAgent()
        self.audio = AG.AudioAgent()
        self.visual = AG.VisualAgent()
        self.edit = AG.EditAgent()
        self.review = AG.ReviewAgent()
        self._emit = None
        self._current = ""
        self._should_stop = None

    # ------------------------------------------------------------------
    # 事件通道
    # ------------------------------------------------------------------
    def _log(self, level: str, msg: str, agent: str | None = None):
        self._emit({"type": "log", "level": level, "msg": msg,
                    "agent": agent or self._current,
                    "t": time.strftime("%H:%M:%S")})

    def _status(self, key: str, status: str, detail: str = ""):
        self._emit({"type": "agent", "agent": key, "status": status, "detail": detail})

    def _step(self, index: int, key: str, label: str, note: str = ""):
        self._emit({"type": "step", "index": index, "total": STEP_TOTAL,
                    "agent": key, "label": label, "note": note})
        self._emit({"type": "progress", "value": (index - 1) / STEP_TOTAL})

    def _check_cancel(self):
        if self._should_stop and self._should_stop():
            raise Canceled("任务已取消")

    # ------------------------------------------------------------------
    # 主流程
    # ------------------------------------------------------------------
    def run(self, topic: str, files: list[dict] | None = None,
            source_text: str = "", doc_name: str = "", audience: str = "本科生",
            minutes: float = 4.0, style: str = "calm", theme: str = "deepsea",
            fmt: str = "landscape", illustrations: bool | None = None,
            pid: str | None = None, emit=None, should_stop=None) -> dict:
        self._emit = emit or (lambda e: None)
        self._current = ""
        self._should_stop = should_stop

        topic = (topic or "").strip()
        files = files or []
        # 项目号由调用方指定（Web 端与前端任务号保持完全一致，避免两套 ID）
        pid = pid or f"{time.strftime('%Y%m%d-%H%M%S')}-{_slug(topic)}"
        pdir = os.path.join(config.OUTPUT_DIR, pid)
        os.makedirs(pdir, exist_ok=True)

        started = time.time()
        fspec = config.get_format(fmt)
        self._emit({"type": "start", "project_id": pid, "topic": topic,
                    "steps": AG.AGENT_SPECS})
        self._log("info", f"项目已创建：{pid}")
        self._log("info", f"目标：{topic}｜面向{audience}｜目标时长约 {minutes:.0f} 分钟"
                          f"｜{fspec['name']}（{fspec['w']}×{fspec['h']}）"
                          f"｜剧本来源：{llm_client.llm_label()}")

        # ---------------- ① 文档解析 ----------------
        self._current = "document"
        self._step(1, "document", "文档解析",
                   f"{len(files)} 个文件" if files else "未上传文档，走主题驱动")
        self._status("document", "running")
        parsed_parts, parsed_meta = [], []
        if files:
            for fi, f in enumerate(files, 1):
                self._check_cancel()
                try:
                    info = self.document.parse(f["path"], self._log)
                    parsed_parts.append(info["text"])
                    parsed_meta.append({"name": f.get("name", os.path.basename(f["path"])),
                                        "chars": info["chars"], **info["meta"]})
                except Exception as e:
                    self._log("warning", f"「{f.get('name')}」解析失败：{e}")
            if parsed_parts:
                merged = "\n\n".join(parsed_parts)
                source_text = (merged + "\n\n" + source_text).strip()
                doc_name = "、".join(m["name"] for m in parsed_meta)
                self._status("document", "done", f"{sum(m['chars'] for m in parsed_meta)} 字")
            else:
                self._status("document", "failed", "全部文件解析失败，改用主题驱动")
        else:
            self._log("思考", "本次没有上传文档，跳过解析环节，直接由主题驱动生成……")
            self._status("document", "skip", "未上传文档")
        self._emit({"type": "docs", "items": parsed_meta})

        # ---------------- ② 知识结构化 ----------------
        self._check_cancel()
        self._current = "structure"
        self._step(2, "structure", "知识结构化")
        self._status("structure", "running")
        fields, structure, source = self.structure.blueprint(
            topic, source_text, self._log, audience, minutes, style, doc_name)
        self._status("structure", "done", f"{len(structure['shots'])} 个分镜")
        self._emit({"type": "outline", "outline": structure["outline"],
                    "subject": structure.get("subject", "")})

        # ---------------- ③ 分镜脚本 ----------------
        self._check_cancel()
        self._current = "script"
        self._step(3, "script", "分镜脚本")
        self._status("script", "running")
        plan = self.script.write(topic, fields, structure, source_text, self._log,
                                 audience, minutes, style, source)
        plan.update({"project_id": pid, "doc_name": doc_name, "audience": audience,
                     "style": style, "theme": theme, "fmt": fmt,
                     "illustrations": config.ILLUSTRATIONS if illustrations is None
                     else bool(illustrations)})
        self._save_json(os.path.join(pdir, "plan.json"), plan)
        self._status("script", "done", f"{len(plan['shots'])} 镜 / {plan['minutes']} 分钟")
        self._emit({"type": "plan", "title": plan["title"], "subject": plan.get("subject", ""),
                    "fmt": fmt,
                    "shots": [{"index": s["index"], "scene": s["scene"],
                               "layout": s["layout"], "title": s["title"],
                               "bullets": s["bullets"], "narration": s["narration"],
                               "seconds": s["seconds"],
                               "visual_kind": s.get("visual_kind", "")} for s in plan["shots"]],
                    "source": plan["source"], "minutes": plan["minutes"],
                    "keywords": plan.get("keywords", [])})

        # ---------------- ④ 配音配乐 ----------------
        self._check_cancel()
        self._current = "audio"
        self._step(4, "audio", "配音配乐")
        self._status("audio", "running")
        metas, bgm = self.audio.synthesize(plan, pdir, self._log, fmt=fmt)
        self._status("audio", "done",
                     f"{len(metas)} 段 · {sum(m['duration'] for m in metas):.0f}s")

        # ---------------- ⑤ 画面生成 ----------------
        self._check_cancel()
        self._current = "visual"
        self._step(5, "visual", "画面生成")
        self._status("visual", "running")
        images = self.visual.render(plan, pdir, self._log, theme=theme, fmt=fmt,
                                    illustrations=illustrations)
        self._status("visual", "done", f"{len(images)} 张画面")

        # ---------------- ⑥ 剪辑合成 ----------------
        self._check_cancel()
        self._current = "edit"
        self._step(6, "edit", "剪辑合成")
        self._status("edit", "running")
        result = self.edit.compose(images, metas, pdir, self._log, True, bgm,
                                  tag="v1", fmt=fmt)
        self._status("edit", "done", f"{result['duration']:.0f}s")

        # ---------------- ⑦ 质检 + 反思回退 ----------------
        self._current = "review"
        self._step(7, "review", "质检打分")
        self._status("review", "running")
        rounds = []
        review = self.review.review(plan, images, metas, result, self._log)
        review["round"] = 1
        rounds.append(review)
        self._emit({"type": "review", **review})

        if not review["pass"]:
            self._status("review", "retry", f"得分 {review['score']}，启动定向回退")
            self._log("warning", "质检未通过 → 进入反思模式：只重做被判不合格的环节，"
                                 "不整条重跑（省 Token、省时间）")
            fixed = self._rework(review, plan, pdir, metas, images, theme, fmt,
                                 illustrations)
            metas, images = fixed["metas"], fixed["images"]
            self._check_cancel()
            self._current = "edit"
            self._status("edit", "retry", "重做 V2")
            self._log("行动", "按修复结果重新剪辑合成（V1 → V2）")
            result = self.edit.compose(images, metas, pdir, self._log, True,
                                       bgm, tag="v2", fmt=fmt)
            self._status("edit", "done", f"{result['duration']:.0f}s（V2）")
            self._current = "review"
            review = self.review.review(plan, images, metas, result, self._log)
            review["round"] = 2
            rounds.append(review)
            self._status("review", "done" if review["pass"] else "failed",
                         f"V2 得分 {review['score']}")
            self._emit({"type": "review", **review})
        else:
            self._status("review", "done", f"得分 {review['score']}")

        # ---------------- 收尾 ----------------
        self._emit({"type": "progress", "value": 1.0})
        frames = sorted(f for f in os.listdir(os.path.join(pdir, "frames"))
                        if f.startswith("shot_") and f.endswith(".png")) \
            if os.path.isdir(os.path.join(pdir, "frames")) else []
        final = {
            "project_id": pid,
            "title": plan["title"],
            "subject": plan.get("subject", ""),
            "audience": audience,
            "source": plan["source"],
            "keywords": plan.get("keywords", []),
            "minutes": plan["minutes"],
            "theme": theme,
            "style": style,
            "fmt": fmt,
            "illustrations": config.ILLUSTRATIONS if illustrations is None
            else bool(illustrations),
            "format_name": fspec["name"],
            "resolution": f"{fspec['w']}×{fspec['h']}",
            "doc_name": doc_name,
            "documents": parsed_meta,
            "engine": sorted({m["engine"] for m in metas}),
            "shots": [{"index": s["index"], "scene": s["scene"], "layout": s["layout"],
                       "title": s["title"], "bullets": s["bullets"],
                       "narration": s["narration"], "seconds": s["seconds"],
                       "visual_kind": s.get("visual_kind", "")}
                      for s in plan["shots"]],
            "images": frames,
            "duration": result["duration"],
            "size_mb": round(os.path.getsize(result["final"]) / 1024 / 1024, 2),
            "review": review,
            "review_rounds": rounds,
            "elapsed": round(time.time() - started, 1),
            "has_nosub": os.path.exists(result["nosub"]),
        }
        self._save_json(os.path.join(pdir, "project.json"), final)
        self._log("success", f"全部完成：{final['duration']:.0f}s 成片，"
                             f"质检 {review['score']} 分，耗时 {final['elapsed']:.0f}s")
        self._emit({"type": "result", "data": final})
        return final

    # ------------------------------------------------------------------
    # 反思回退：定向修复
    # ------------------------------------------------------------------
    def _rework(self, review: dict, plan: dict, pdir: str, metas: list[dict],
                images: list[str], theme: str, fmt: str = "landscape",
                illustrations: bool | None = None) -> dict:
        codes = {i["code"] for i in review["issues"]}
        shots = plan["shots"]

        # 1) 语音过短 / 旁白为空 → 放慢语速重做这些分镜
        audio_codes = {"audio_short", "narration_empty", "content_thin"}
        if codes & audio_codes:
            bad = [m["index"] for m in metas
                   if float(m.get("duration") or 0) < 0.8 or len(m.get("text") or "") < 15]
            bad = bad or [m["index"] for m in metas if m["index"] in
                          {c.get("shot") for c in review["issues"] if c.get("shot")}]
            targets = bad or [min(metas, key=lambda m: m["duration"])["index"]]
            self._log("行动", f"定向修复：对分镜 {targets} 放慢语速重新配音（+0%）")
            metas, bgm = self.audio.synthesize(plan, pdir, self._log,
                                               retry_shots=targets, rate="+0%",
                                               base_metas=metas, fmt=fmt)
            self._emit({"type": "rework", "what": "audio", "shots": targets})
        else:
            bgm = os.path.join(pdir, "bgm.wav")
            if not os.path.exists(bgm):
                bgm = None

        # 2) 画面缺失 / 数量不符 → 重渲染
        if codes & {"image_missing", "image_count"}:
            self._log("行动", "定向修复：重新渲染缺失的画面")
            images = self.visual.render(plan, pdir, self._log, theme=theme, fmt=fmt,
                                        illustrations=illustrations)
            self._emit({"type": "rework", "what": "visual", "shots": []})

        # 3) 字幕缺失 → 重建 SRT
        if codes & {"subtitle_missing", "duration_mismatch"}:
            self._log("行动", "定向修复：依据新音频时长重建字幕时间轴")
            self.audio.build_srt(metas, pdir, fmt=fmt)
            self._emit({"type": "rework", "what": "subtitle", "shots": []})

        return {"metas": metas, "images": images, "bgm": bgm}

    # ------------------------------------------------------------------
    @staticmethod
    def _save_json(path: str, data):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)


def safe_slug(text: str, max_len: int = 20) -> str:
    """把任意标题变成安全的目录名片段"""
    return _slug(text, max_len)


def _slug(text: str, max_len: int = 20) -> str:
    slug = re.sub(r"[^\w\u4e00-\u9fff]+", "-", text or "").strip("-")
    return slug[:max_len] or "project"
