# -*- coding: utf-8 -*-
"""7 个分工 Agent —— 对应设计图中的「执行层」

① DocumentParserAgent  文档解析    提取 PDF / PPT / Word / TXT 文本与结构
② StructureAgent       知识结构化  校验分镜数、统一版式、规划时长与节奏
③ ScriptAgent          分镜脚本    调大模型或内置引擎，产出旁白稿 + 画面指令
④ AudioAgent           配音字幕    edge-tts/SAPI 配音 + SRT 字幕时间轴 + 背景音乐
⑤ VisualAgent          画面生成    Pillow 直接渲染 1920×1080 幻灯片
⑥ EditAgent            剪辑合成    FFmpeg 合成画面+配音+BGM+字幕 → MP4
⑦ ReviewAgent          质检打分    反思模式：不合格自动回退重做（V1 → V2）

每个 Agent 统一用 (思考 → 行动 → 观察) 三段式汇报，便于前端展示 Agent 的
决策过程，而不是一个黑盒进度条。
"""
from __future__ import annotations

import os
import re
import shutil

from . import config
from . import illustrate
from . import knowledge as KB
from . import llm_client
from . import media, music, slides

MAX_SHOTS = 12
MIN_SHOTS = 8


# ======================================================================
# 公共工具
# ======================================================================
def fmt_ts(sec: float) -> str:
    """秒 → SRT 时间戳 00:00:00,000"""
    sec = max(0.0, float(sec))
    h = int(sec // 3600)
    m = int(sec % 3600 // 60)
    s = int(sec % 60)
    ms = int(round((sec - int(sec)) * 1000))
    if ms == 1000:
        s, ms = s + 1, 0
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def split_cues(text: str, line_chars: int = None, max_lines: int = None) -> list[str]:
    """把一段旁白切成若干条字幕（每条最多 max_lines 行）"""
    line_chars = line_chars or config.SUBTITLE_MAX_CHARS
    max_lines = max_lines or config.SUBTITLE_MAX_LINES
    per_cue = line_chars * max_lines
    text = re.sub(r"\s+", "", text or "")
    if not text:
        return []
    # 优先在标点处断句，避免把词切开
    parts = re.split(r"(?<=[。！？；，、])", text)
    cues, cur = [], ""
    for p in parts:
        if len(cur) + len(p) <= per_cue:
            cur += p
        else:
            if cur:
                cues.append(cur)
            while len(p) > per_cue:          # 超长句强制切分
                cues.append(p[:per_cue])
                p = p[per_cue:]
            cur = p
    if cur:
        cues.append(cur)
    return cues


def wrap_cue(cue: str, line_chars: int = None) -> str:
    """把一条字幕折成最多 2 行（供 SRT 内部换行）"""
    line_chars = line_chars or config.SUBTITLE_MAX_CHARS
    if len(cue) <= line_chars:
        return cue
    mid = (len(cue) + 1) // 2
    # 就近找标点断行
    for offset in range(0, min(8, len(cue) // 2)):
        for pos in (mid - offset, mid + offset):
            if 0 < pos < len(cue) and cue[pos - 1] in "。！？；，、,.!?;":
                return cue[:pos] + "\n" + cue[pos:]
    return cue[:mid] + "\n" + cue[mid:]


# ======================================================================
# ① 文档解析
# ======================================================================
class DocumentParserAgent:
    key = "document"
    name = "文档解析"
    icon = "①"
    desc = "提取 PDF / Word / PPT 文本与结构"

    def parse(self, file_path: str, log=None) -> dict:
        log = log or (lambda *a, **k: None)
        log("思考", f"收到文件「{os.path.basename(file_path)}」，判断类型并选择解析工具……")
        ext = os.path.splitext(file_path)[1].lower()
        log("行动", f"调用 {ext} 解析器读取正文与结构")
        if ext == ".pdf":
            text, meta = self._pdf(file_path)
        elif ext in (".ppt", ".pptx"):
            text, meta = self._ppt(file_path)
        elif ext in (".doc", ".docx"):
            text, meta = self._doc(file_path)
        elif ext in (".txt", ".md", ".markdown"):
            with open(file_path, encoding="utf-8", errors="replace") as f:
                text = f.read()
            meta = {"段落数": len([p for p in text.split("\n") if p.strip()])}
        else:
            raise ValueError(f"暂不支持的文件类型：{ext}")

        text = re.sub(r"[ \t\u3000]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        if not text:
            raise ValueError("未能从文档中提取到文本（可能是扫描版 PDF 或纯图片 PPT）")

        kws = KB.extract_keywords(text, topk=10)
        log("观察", f"提取文本 {len(text)} 字" +
            (f"，识别到关键词：{'、'.join(kws[:6])}" if kws else ""))
        return {"text": text, "chars": len(text), "meta": meta, "keywords": kws}

    def _pdf(self, path):
        import pdfplumber
        parts, pages = [], 0
        with pdfplumber.open(path) as pdf:
            pages = len(pdf.pages)
            for page in pdf.pages[:30]:
                parts.append(page.extract_text() or "")
        return "\n".join(parts), {"页数": pages}

    def _ppt(self, path):
        from pptx import Presentation
        prs = Presentation(path)
        parts = []
        for slide in prs.slides:
            for shape in slide.shapes:
                if shape.has_text_frame and shape.text_frame.text.strip():
                    parts.append(shape.text_frame.text)
            if slide.has_notes_slide and slide.notes_slide.notes_text_frame:
                parts.append(slide.notes_slide.notes_text_frame.text)
        return "\n".join(parts), {"幻灯片数": len(prs.slides)}

    def _doc(self, path):
        import docx
        d = docx.Document(path)
        parts = [p.text for p in d.paragraphs if p.text.strip()]
        for table in d.tables:
            for row in table.rows:
                cells = [c.text.strip() for c in row.cells if c.text.strip()]
                if cells:
                    parts.append(" | ".join(cells))
        return "\n".join(parts), {"段落数": len(parts), "表格数": len(d.tables)}


# ======================================================================
# ② 知识结构化
# ======================================================================
class StructureAgent:
    key = "structure"
    name = "知识结构化"
    icon = "②"
    desc = "生成大纲、知识要点与时长规划"

    LAYOUT_ORDER = ["cover", "quote", "quote", "points", "points", "steps",
                    "points", "points", "compare", "steps", "summary", "ending"]

    def blueprint(self, topic: str, source_text: str, log, audience: str = "本科生",
                  minutes: float = 4.0, style: str = "calm",
                  doc_name: str = "") -> tuple[dict, dict, str]:
        """产出「讲什么」（内容字段）+「怎么排」（分镜骨架）"""
        log("思考", f"围绕「{topic}」做知识结构化：定大纲、拆要点、排时长……")

        # 先走本地引擎拿到兜底内容，保证后续任何环节失败都有东西可用
        fields, source = KB.build_fields(topic, source_text, audience, minutes,
                                         style, doc_name)

        # 配了大模型就用它来做「讲什么」这一步 —— 这一步的质量决定了整支视频的内容上限
        if llm_client.llm_available():
            log("行动", f"调用 {config.LLM_MODEL} 提炼知识结构"
                        + (f"（参考文档 {len(source_text)} 字）" if source_text else ""))
            try:
                fields = llm_client.generate_fields(topic, source_text, audience, minutes)
                source = f"大模型内容生成（{config.LLM_MODEL}）"
                log("观察", f"大模型产出知识结构：主题「{fields.get('title')}」"
                            f"｜{len(fields.get('core', []))} 个核心要素")
            except Exception as e:                  # noqa: BLE001
                log("观察", f"大模型调用失败，已自动降级内置引擎：{str(e)[:150]}")
        elif source.startswith("文档驱动"):
            log("行动", f"从文档中提炼 {len(fields.get('_keywords', []))} 个关键词，"
                        f"按教学逻辑重组为知识结构")
        else:
            log("行动", f"匹配学科骨架 → {fields.get('subject', '通识讲解')}")

        structure = KB.plan_structure(topic, fields, audience, minutes, style)
        shots = structure["shots"]

        # 分镜数量控制在 8~12（设计图要求）
        if len(shots) > MAX_SHOTS:
            head, tail, mid = shots[:2], shots[-2:], shots[2:-2]
            mid = sorted(mid, key=lambda s: -len(s.get("bullets", [])))[:MAX_SHOTS - 4]
            shots = head + mid + tail
            log("行动", f"分镜过多，合并次要内容 → 保留 {len(shots)} 个分镜")
        structure["shots"] = shots
        for i, s in enumerate(shots):
            s["index"] = i + 1

        layouts = " → ".join(s["layout"] for s in shots)
        outline = "、".join(s["scene"] for s in shots)
        log("观察", f"结构确定：{len(shots)} 个分镜｜版式 {layouts}")
        log("观察", f"教学大纲：{outline}")
        return fields, structure, source


# ======================================================================
# ③ 分镜脚本
# ======================================================================
class ScriptAgent:
    key = "script"
    name = "分镜脚本"
    icon = "③"
    desc = "为每个分镜撰写旁白稿"

    def write(self, topic: str, fields: dict, structure: dict, source_text: str,
              log, audience: str = "本科生", minutes: float = 4.0,
              style: str = "calm", source: str = "") -> dict:
        shots = structure["shots"]
        budget = KB.narration_budget(minutes * 60, len(shots))
        if llm_client.llm_available():
            log("思考", f"按已确定的结构，为大模型提供 {len(shots)} 个分镜的写作指令……")
            log("行动", f"时长预算：目标 {minutes:.0f} 分钟 ÷ {len(shots)} 镜 "
                        f"→ 每镜旁白 {budget[0]}~{budget[1]} 字")
            log("行动", f"调用 {config.LLM_MODEL} 逐镜撰写旁白稿")
            try:
                shots = llm_client.write_narration(topic, shots, source_text, audience,
                                                   budget=budget, target_sec=minutes * 60)
                source = f"大模型生成（{config.LLM_MODEL}）"
                log("观察", "大模型旁白稿完成")
            except Exception as e:
                log("观察", f"大模型写作失败，降级内置引擎：{str(e)[:150]}")
                shots = KB.write_narration(topic, fields, shots, audience, minutes, style)
        else:
            log("思考", "未配置大模型 Key，使用内置教学脚本引擎逐镜撰写旁白……")
            log("行动", f"时长预算：目标 {minutes:.0f} 分钟 ÷ {len(shots)} 镜 "
                        f"→ 每镜旁白 {budget[0]}~{budget[1]} 字")
            log("行动", "按「先结论后展开」的口语化讲法生成旁白稿")
            shots = KB.write_narration(topic, fields, shots, audience, minutes, style)
            source = source or "内置教学脚本引擎"
            builtin_sec = sum(media.estimate_duration(s["narration"]) for s in shots)
            if builtin_sec < minutes * 60 * 0.8:
                log("观察", f"内置知识库素材已讲满（约 {builtin_sec / 60:.1f} 分钟）。"
                            f"要做到 {minutes:.0f} 分钟：在右上角「⚙ 大模型设置」里配 Key，"
                            f"或上传一份更详细的文档作为素材。")

        for s in shots:
            s["seconds"] = s.get("seconds") or media.estimate_duration(s["narration"])
        plan = KB.finalize(topic, fields, structure, shots, source,
                           audience=audience, minutes=minutes)
        actual = sum(s.get("seconds", 0) for s in shots) / 60.0
        chars = len(plan.get("script", ""))
        log("观察", f"脚本完成：{len(shots)} 个分镜，旁白 {chars} 字，"
                    f"预估 {plan['minutes']} 分钟（目标 {minutes:.0f} 分钟）"
                    f"｜生成方式：{plan['source']}")
        if actual > minutes * 1.2:
            log("观察", f"仍超出目标时长，已按句裁短最长镜头的旁白")
        return plan


# ======================================================================
# ④ 配音 + 字幕 + 配乐
# ======================================================================
class AudioAgent:
    key = "audio"
    name = "配音配乐"
    icon = "④"
    desc = "TTS 旁白 + SRT 字幕时间轴 + 背景音乐"

    def synthesize(self, plan: dict, project_dir: str, log,
                   retry_shots: list[int] | None = None,
                   rate: str | None = None,
                   base_metas: list[dict] | None = None,
                   fmt: str = "landscape") -> tuple[list[dict], str | None]:
        """合成旁白并生成 SRT / BGM。

        retry_shots：只重做这些分镜（质检回退时用），其余复用 base_metas 的结果，
                     这样「自动重做」不会白白浪费已完成的配音。
        """
        shots = plan["shots"]
        sdir = os.path.join(project_dir, "shots")
        os.makedirs(sdir, exist_ok=True)
        prev = {m["index"]: m for m in (base_metas or [])}
        metas: dict[int, dict] = dict(prev)
        todo = [s for s in shots if not retry_shots or s["index"] in retry_shots
                or s["index"] not in prev]

        log("思考", f"为 {len(todo)} 个分镜合成旁白"
                    + ("（质检回退后重做语音）" if retry_shots else "……"))

        for s in todo:
            i = s["index"]
            mp3 = os.path.join(sdir, f"shot_{i:02d}.mp3")
            res = media.synthesize(s["narration"], mp3, rate=rate or config.TTS_RATE)
            s["seconds"] = res["duration"]
            metas[i] = {"index": i, "path": res["path"], "duration": res["duration"],
                        "engine": res["engine"], "scene": s["scene"],
                        "text": s["narration"]}
            log("行动", f"分镜{i:02d}「{s['scene']}」配音完成 "
                        f"（{res['engine']}，{res['duration']:.1f}s）")

        for s in shots:                      # 补齐 seconds
            if s["index"] in metas:
                s["seconds"] = metas[s["index"]]["duration"]

        engines = {m["engine"] for m in metas.values() if m}
        log("观察", f"配音就绪：{len(metas)} 段，引擎 {'/'.join(sorted(engines))}，"
                    f"合计 {sum(m['duration'] for m in metas.values() if m):.0f}s")

        ordered = [metas[s["index"]] for s in shots if s["index"] in metas]
        srt_path = self.build_srt(ordered, project_dir, fmt=fmt)
        log("行动", f"生成字幕（SRT + ASS）：{self._count_srt(srt_path)} 条")

        bgm = None
        if config.BGM_ENABLED:
            total = sum(m["duration"] for m in ordered) + config.SHOT_GAP * len(ordered)
            bgm = music.build_bgm(total, os.path.join(project_dir, "bgm.wav"),
                                  style=plan.get("style", "calm"))
            log("行动", f"合成背景音乐：{total:.0f}s（{plan.get('style', 'calm')} 风格）")
        return ordered, bgm

    # ---- SRT ----
    def build_srt(self, metas: list[dict], project_dir: str,
                  fmt: str = "landscape") -> str:
        """同时产出两份字幕：
          · narration.srt —— 通用字幕文件，供下载/播放器使用
          · narration.ass —— 自带画布尺寸（PlayRes=视频分辨率）的硬字幕源，
                            这样 FontSize / MarginV 就是真实像素，
                            避免 libass 按默认 288 高坐标空间把字幕放大到离谱。
        """
        lines, cursor, n = [], 0.0, 0
        for m in metas:
            text = m.get("text") or ""
            dur = max(0.5, float(m.get("duration") or 1.0))
            cues = split_cues(text) or [text]
            weights = [max(1, len(c)) for c in cues]
            wsum = sum(weights)
            t = cursor
            for cue, w in zip(cues, weights):
                seg = dur * w / wsum
                n += 1
                lines.append(str(n))
                lines.append(f"{fmt_ts(t)} --> {fmt_ts(t + seg)}")
                lines.append(wrap_cue(cue))
                lines.append("")
                t += seg
            m["cue_count"] = len(cues)
            cursor += dur + config.SHOT_GAP
        path = os.path.join(project_dir, "narration.srt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        self._write_ass(lines, project_dir, fmt)
        return path

    def _write_ass(self, srt_lines: list[str], project_dir: str,
                   fmt: str) -> str:
        """把 SRT 转成 ASS，并用 PlayRes 锁定字幕坐标空间"""
        fspec = config.get_format(fmt)
        blocks, i = [], 0
        while i < len(srt_lines):
            if not srt_lines[i].strip():
                i += 1
                continue
            try:
                start, _, end = srt_lines[i + 1].partition(" --> ")
                text = srt_lines[i + 2]
            except IndexError:
                break
            blocks.append((start.strip(), end.strip(), text.replace("\n", "\\N")))
            i += 4

        def ass_ts(ts: str) -> str:
            """00:00:01,500 → 0:00:01.50"""
            hms, _, ms = ts.partition(",")
            h, m, s = hms.split(":")
            return f"{int(h)}:{m}:{s}.{ms[:2]}"

        head = (
            "[Script Info]\n"
            "ScriptType: v4.00+\n"
            f"PlayResX: {fspec['w']}\n"
            f"PlayResY: {fspec['h']}\n"
            "WrapStyle: 2\n"
            "ScaledBorderAndShadow: yes\n"
            "YCbCr Matrix: TV.709\n\n"
            "[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
            "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
            "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding\n"
            f"Style: Default,{config.subtitle_font_name()},{fspec['sub_font']},"
            "&H00FFFFFF,&H000000FF,&H0020120A,&H80000000,"
            "0,0,0,0,100,100,0,0,1,3,0,2,"
            f"48,48,{fspec['sub_margin']},1\n\n"
            "[Events]\n"
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, "
            "MarginV, Effect, Text\n")
        body = "".join(
            f"Dialogue: 0,{ass_ts(s)},{ass_ts(e)},Default,,0,0,0,,{t}\n"
            for s, e, t in blocks)
        path = os.path.join(project_dir, "narration.ass")
        with open(path, "w", encoding="utf-8") as f:
            f.write(head + body)
        return path

    @staticmethod
    def _count_srt(path: str) -> int:
        try:
            with open(path, encoding="utf-8") as f:
                return f.read().count("-->")
        except OSError:
            return 0

    def total_duration(self, metas: list[dict]) -> float:
        return sum(m["duration"] for m in metas) + config.SHOT_GAP * len(metas)


# ======================================================================
# ⑤ 画面生成
# ======================================================================
class VisualAgent:
    key = "visual"
    name = "画面生成"
    icon = "⑤"
    desc = "Pillow 渲染教学幻灯片，每一屏自动配结构化插图"

    def render(self, plan: dict, project_dir: str, log,
               theme: str = "deepsea", fmt: str = "landscape",
               illustrations: bool | None = None) -> list[str]:
        shots = plan["shots"]
        total = len(shots)
        use_art = config.ILLUSTRATIONS if illustrations is None else bool(illustrations)
        self._use_art = use_art
        fspec = config.get_format(fmt)
        n_art = sum(1 for s in shots if s.get("visual_kind")) if use_art else 0
        log("思考", f"按 {total} 个分镜渲染 {fspec['name']} 画面"
                    f"（{fspec['w']}×{fspec['h']}）"
                    + (f"，并自动生成 {n_art} 张结构化插图" if n_art else "") + "……")
        fdir = os.path.join(project_dir, "frames")
        os.makedirs(fdir, exist_ok=True)
        renderer = slides.SlideRenderer(fmt=fmt, theme_name=theme,
                                       subject=plan.get("subject", ""),
                                       theme_key=plan.get("style", "calm"))

        images = []
        for s in shots:
            out = os.path.join(fdir, f"shot_{s['index']:02d}.png")
            art = self._make_art(renderer, s)
            renderer.render_shot(s, s["index"], total, out, art)
            images.append(out)
            kind = self._art_kind or "—"
            art_note = f" · 配图 {kind}" if art is not None else ""
            log("行动", f"分镜{s['index']:02d} 渲染完成 · 版式 {s['layout']}{art_note}")
        log("观察", f"画面就绪：{len(images)} 张 PNG（{theme} 主题 · {fspec['name']}）")
        return images

    # ------------------------------------------------------------------
    def _make_art(self, renderer: slides.SlideRenderer, shot: dict):
        """按分镜语义生成插图（无插图需求时返回 None）

        目标是**每一屏都有配图**：正文页一律「左文字 + 右插图」，
        封面/片尾用整屏装饰主视觉；流程页与对照页本身就是「卡片 + 箭头」
        的图形版式，横版下再塞右栏插图反而挤，所以用装饰层垫底。
        """
        kind = shot.get("visual_kind")
        self._art_kind = kind
        if not (getattr(self, "_use_art", config.ILLUSTRATIONS) and kind):
            return None
        layout = (shot.get("layout") or "points").lower()

        # 装饰性主视觉：整屏透明叠加，不需要单独尺寸
        if kind == "motif":
            return renderer.artist.motif(seed=shot.get("index", 0))

        # 横版的流程页 / 对照页：原生版式已经是图形，插图退化为背景装饰层
        if layout in ("steps", "compare") and not renderer.portrait:
            self._art_kind = "背景装饰"
            return renderer.artist.motif(seed=shot.get("index", 0))

        w, h = renderer.art_size(layout, kind)
        artist = illustrate.Artist(renderer.theme, (w, h), renderer.S)
        bullets = shot.get("bullets") or []
        scene = shot.get("scene") or shot.get("title") or ""

        if kind == "concept":
            # 中心节点用分镜场景名（不要用标题，否则和幻灯片大标题重复）
            return artist.concept_map(scene, bullets)
        if kind == "flow":
            # 说明文字由版面左侧/下方的文字栏承担，插图只画步骤名
            return artist.flow_chain(bullets, with_desc=False)
        if kind == "tags":
            return artist.tag_cloud(bullets)
        if kind == "compare":
            raw = [str(b) for b in bullets]
            half = max(1, len(raw) // 2)
            left = [str(b).split("|")[0] for b in raw[:half]]
            right = [(str(b).split("|")[1] if "|" in str(b) else str(b))
                     for b in raw[half:]]
            return artist.split_compare(left, right)
        if kind == "rail":
            return artist.index_rail(bullets, scene)
        if kind == "mind":
            return artist.radial_index(bullets, scene)
        if kind == "check":
            # 竖版流程页会用插图整屏承载内容，所以要连说明文字一起画
            return artist.flow_chain(bullets, with_desc=renderer.portrait)
        if kind == "spotlight":
            return artist.spotlight(scene)
        return None


# ======================================================================
# ⑥ 剪辑合成
# ======================================================================
class EditAgent:
    key = "edit"
    name = "剪辑合成"
    icon = "⑥"
    desc = "FFmpeg 合成画面 + 配音 + BGM + 字幕 → MP4"

    def compose(self, images: list[str], metas: list[dict], project_dir: str,
                log, with_subtitle: bool = True, bgm: str | None = None,
                tag: str = "v1", fmt: str = "landscape") -> dict:
        exe = media.ffmpeg_exe()
        if not exe:
            raise RuntimeError("未找到 ffmpeg，请执行 pip install imageio-ffmpeg")
        fspec = config.get_format(fmt)
        fw, fh = fspec["w"], fspec["h"]

        gap = config.SHOT_GAP
        clips_dir = os.path.join(project_dir, "clips")
        os.makedirs(clips_dir, exist_ok=True)
        clips, total = [], 0.0

        # 编码参数（含线程数限制，见 config.ffmpeg_threads 的注释）
        enc = ["-c:v", config.VIDEO_CODEC, "-tune", "stillimage",
               "-crf", config.CRF, "-preset", config.PRESET]
        th = config.ffmpeg_threads()
        if th:
            enc += ["-threads", str(th)]

        log("思考", f"逐分镜合成镜头：画面定格 + 配音轨，共 {len(images)} 段"
                    f"（preset {config.PRESET}" + (f"，{th} 线程" if th else "") + "）")
        for i, (img, meta) in enumerate(zip(images, metas)):
            dur = round(meta["duration"] + gap, 3)
            total += dur
            clip = os.path.join(clips_dir, f"clip_{i + 1:02d}.mp4")
            vf = [f"scale={fw}:{fh}", "setsar=1", "format=yuv420p"]
            af = [f"apad=pad_dur={gap}"]
            if i == 0:
                vf.append("fade=t=in:st=0:d=0.7")
                af.append("afade=t=in:st=0:d=0.4")
            if i == len(images) - 1:
                vf.append(f"fade=t=out:st={max(0.0, dur - 0.7):.2f}:d=0.7")
                af.append(f"afade=t=out:st={max(0.0, dur - 0.7):.2f}:d=0.7")
            media.ff(
                "-loop", "1", "-i", img, "-i", meta["path"],
                "-t", f"{dur:.3f}",
                "-vf", ",".join(vf), "-af", ",".join(af),
                "-r", str(config.FPS), *enc,
                "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2",
                "-movflags", "+faststart", clip, timeout=600)
            clips.append(clip)
            log("行动", f"镜头 {i + 1:02d}/{len(images)} 合成完成（{dur:.1f}s）")

        # 拼接
        concat = os.path.join(project_dir, "concat.txt")
        with open(concat, "w", encoding="utf-8") as f:
            for c in clips:
                f.write("file '%s'\n" % c.replace("\\", "/").replace("'", "'\\''"))
        raw = os.path.join(project_dir, "raw.mp4")
        media.ff("-f", "concat", "-safe", "0", "-i", concat, "-c", "copy",
                 "-movflags", "+faststart", raw, timeout=600)
        log("行动", f"拼接 {len(clips)} 个镜头 → 无字幕版母带（{total:.1f}s）")

        # 混入背景音乐
        mixed = raw
        if bgm and os.path.exists(bgm):
            mixed = os.path.join(project_dir, "mixed.mp4")
            fade_out = max(0.0, total - 2.5)
            media.ff(
                "-i", raw, "-i", bgm,
                "-filter_complex",
                f"[1:a]volume={config.BGM_VOLUME},"
                f"afade=t=in:st=0:d=2,afade=t=out:st={fade_out:.2f}:d=2.5[bg];"
                f"[0:a][bg]amix=inputs=2:duration=first:normalize=0[a]",
                "-map", "0:v", "-map", "[a]",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
                "-movflags", "+faststart", mixed, timeout=600)
            log("行动", f"混入背景音乐（音量 {int(config.BGM_VOLUME * 100)}%）")

        nosub = os.path.join(project_dir, "final_nosub.mp4")
        shutil.copyfile(mixed, nosub)

        final = nosub
        if with_subtitle:
            final = os.path.join(project_dir, "final.mp4")
            self._burn_subtitles(mixed, project_dir, final, log, fspec)
        else:
            shutil.copyfile(mixed, final)

        log("观察", f"成片导出完成：{os.path.basename(final)}"
                    f"（{total:.1f}s，{fw}×{fh}，{os.path.getsize(final) / 1024 / 1024:.1f} MB）")
        return {"final": final, "nosub": nosub, "raw": raw,
                "duration": round(total, 2), "clips": len(clips), "tag": tag,
                "fmt": fmt}

    def _burn_subtitles(self, src: str, project_dir: str, out: str, log,
                        fspec: dict | None = None) -> str:
        """烧录硬字幕。

        优先用自建的 narration.ass：它在文件头显式声明了 PlayResX/PlayResY
        （等于视频分辨率），所以 FontSize、MarginV 都是真实像素。
        若直接用 SRT，libass 会按默认 288 高的坐标空间缩放，
        字幕会被放大到画面中部——这正是之前踩过的坑。
        """
        fspec = fspec or config.get_format("landscape")
        ass = os.path.join(project_dir, "narration.ass")
        srt = os.path.join(project_dir, "narration.srt")
        if not os.path.exists(ass) and not os.path.exists(srt):
            log("观察", "未找到字幕文件，跳过字幕烧录")
            shutil.copyfile(src, out)
            return out

        if os.path.exists(ass):
            vf = "subtitles=narration.ass"
        else:
            style = (f"FontName={config.subtitle_font_name()},"
                     f"FontSize={fspec.get('sub_font', config.SUBTITLE_FONT_SIZE)},"
                     f"PrimaryColour=&H00FFFFFF,OutlineColour=&H0020120A,BorderStyle=1,"
                     f"Outline=3,Shadow=0,Alignment=2,"
                     f"MarginV={fspec.get('sub_margin', config.SUBTITLE_MARGIN_V)}")
            vf = f"subtitles=narration.srt:force_style='{style}'"
        th = config.ffmpeg_threads()
        # 这一步要把整片重新编码一遍，是整条流水线里最慢的单个调用。
        # 先打一行日志并说明耗时，否则前端看起来像卡死了（期间不会有任何新事件）。
        log("思考", f"烧录中文字幕：整片重编码，是本流程最耗时的一步"
                    f"（preset {config.PRESET}" + (f"，{th} 线程" if th else "") + "，请耐心等待）")
        media.ff("-i", os.path.basename(src), "-vf", vf,
                 "-c:v", config.VIDEO_CODEC, "-crf", config.CRF,
                 "-preset", config.PRESET, *(["-threads", str(th)] if th else []),
                 "-c:a", "copy",
                 "-movflags", "+faststart", os.path.basename(out),
                 timeout=900, cwd=project_dir)
        log("行动", f"烧录中文字幕（{'ASS' if os.path.exists(ass) else 'SRT'} → 硬字幕）")
        return out


# ======================================================================
# ⑦ 质检（反思模式）
# ======================================================================
class ReviewAgent:
    key = "review"
    name = "质检打分"
    icon = "⑦"
    desc = "检查音画同步/字幕/完整性，不合格自动回退重做"

    def review(self, plan: dict, images: list[str], metas: list[dict],
               result: dict, log) -> dict:
        log("思考", "启动成片质检：逐项核对完整性、音画同步与字幕覆盖……")
        checks: list[dict] = []

        def add(code, name, ok, detail=""):
            checks.append({"code": code, "name": name, "ok": bool(ok), "detail": detail})

        shots = plan.get("shots", [])
        # 1) 画面数量
        add("image_count", "画面数量与分镜一致",
            len(images) == len(shots),
            f"{len(images)} 张画面 / {len(shots)} 个分镜")
        # 2) 每镜有画面文件
        missing = [i + 1 for i, p in enumerate(images)
                   if not (os.path.exists(p) and os.path.getsize(p) > 3000)]
        add("image_missing", "画面文件完整", not missing,
            f"缺失分镜：{missing}" if missing else "全部正常")
        # 3) 旁白非空
        empty = [m["index"] for m in metas if not (m.get("text") or "").strip()]
        add("narration_empty", "旁白稿非空", not empty,
            f"空旁白分镜：{empty}" if empty else "全部有旁白")
        # 4) 音频时长
        short = [m["index"] for m in metas if float(m.get("duration") or 0) < 0.8]
        add("audio_short", "配音时长合理", not short,
            f"过短分镜：{short}" if short else
            f"最短 {min((m['duration'] for m in metas), default=0):.1f}s")
        # 5) 成片存在
        final = result.get("final")
        size_ok = bool(final) and os.path.exists(final) and os.path.getsize(final) > 50 * 1024
        add("video_missing", "成片文件有效", size_ok,
            f"{os.path.getsize(final) / 1024 / 1024:.1f} MB" if size_ok else "成片缺失或过小")
        # 6) 视频时长 vs 音轨总长
        expect = sum(m["duration"] for m in metas) + config.SHOT_GAP * len(metas)
        real = float(result.get("duration") or 0)
        diff = abs(expect - real)
        add("duration_mismatch", "音画时间轴同步", diff <= 1.0,
            f"预期 {expect:.1f}s / 实际 {real:.1f}s（偏差 {diff:.2f}s）")
        # 7) 字幕覆盖
        srt = os.path.join(os.path.dirname(final or ""), "narration.srt")
        n_sub = 0
        if os.path.exists(srt):
            with open(srt, encoding="utf-8") as f:
                n_sub = f.read().count("-->")
        add("subtitle_missing", "字幕覆盖全部分镜",
            n_sub >= len(metas),
            f"{n_sub} 条字幕 / {len(metas)} 个分镜")
        # 8) 旁白长度（内容充实度）
        too_short = [m["index"] for m in metas if len(m.get("text") or "") < 15]
        add("content_thin", "旁白内容充实", not too_short,
            f"内容过少的分镜：{too_short}" if too_short else "内容充实")

        failed = [c for c in checks if not c["ok"]]
        score = max(0, 100 - 12 * len(failed))
        issues = [{"code": c["code"], "message": f"{c['name']}：{c['detail']}"}
                  for c in failed]

        if failed:
            log("观察", f"质检未通过（得分 {score}）：" +
                        "；".join(c["name"] for c in failed))
            return {"pass": False, "score": score, "issues": issues, "checks": checks}
        log("观察", f"质检通过（得分 {score}）：8 项检查全部合格")
        return {"pass": True, "score": score, "issues": [], "checks": checks}


# ======================================================================
# Agent 注册表（供前端展示七步流水线）
# ======================================================================
AGENT_SPECS = [
    {"key": "document", "icon": "①", "name": "文档解析", "desc": "提取文档文本与结构",
     "tool": "pdfplumber / python-docx / python-pptx"},
    {"key": "structure", "icon": "②", "name": "知识结构化", "desc": "大纲、知识点与时长规划",
     "tool": "规则引擎 + 时长模型"},
    {"key": "script", "icon": "③", "name": "分镜脚本", "desc": "8~12 个分镜 + 旁白稿 + 画面指令",
     "tool": "LLM API / 内置脚本引擎"},
    {"key": "audio", "icon": "④", "name": "配音配乐", "desc": "TTS 旁白 + SRT 字幕 + 背景音乐",
     "tool": "edge-tts / Windows SAPI / numpy"},
    {"key": "visual", "icon": "⑤", "name": "画面生成", "desc": "1920×1080 教学幻灯片",
     "tool": "Pillow（无需 LibreOffice）"},
    {"key": "edit", "icon": "⑥", "name": "剪辑合成", "desc": "画面+配音+BGM+字幕 → MP4",
     "tool": "FFmpeg"},
    {"key": "review", "icon": "⑦", "name": "质检打分", "desc": "不合格自动回退重做 V1→V2",
     "tool": "反思模式质检闭环"},
]
