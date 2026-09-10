# -*- coding: utf-8 -*-
"""内置教学脚本引擎（无需大模型 API Key）

职责：把「一个知识主题」或「一份上传文档」变成一份可直接开拍的教学分镜方案：
    主题/文档 → 教学叙事骨架 → 大纲 → 8~12 个分镜（含版式、要点、旁白稿）

两条生成路径：
  1) 文档驱动：从上传的 PDF/Word/PPT 文本中提炼关键词与关键句，旁白直接引用文档要点；
  2) 主题驱动：命中「学科知识骨架库」则用精编内容，未命中则用通用教学叙事骨架
     + 领域词库扩写（保证内容不空洞，且有明确的教学结构）。

注：本引擎是「规则 + 领域知识库」，不是伪装成 AI。界面会如实标注当前生成方式。
"""
from __future__ import annotations

import re
from collections import Counter

from .media import estimate_duration

# ----------------------------------------------------------------------
# 通用中文停用词 / 虚词（用于关键词抽取）
# ----------------------------------------------------------------------
_STOP = set("的 了 和 与 及 或 在 是 为 对 从 到 把 被 让 使 我们 你们 他们 这 那 有 也 就 都 而 但 并 很 更 最 可以 需要 通过 进行 一个 一种 一些 什么 怎么 如何 以及 因为 所以 如果 那么 这样 那样 同时 已经 能够 不是 没有 还是 为了 对于 关于 其中 由于 从而 因此 并且 但是 例如 比如 包括 主要 重要 基本 相关 不同 各种 以下几个方面".split())
_PUNCT = "，。！？；：、（）《》【】“”‘’—…·,.!?;:()[]<>\"'`~@#$%^&*_+=|\\/ \t\r\n　"


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _norm(text: str) -> str:
    """只规范空白、保留换行 —— 换行是文档里最重要的分段/标题边界"""
    return re.sub(r"[ \t\u3000]+", " ", text or "").strip()


# ----------------------------------------------------------------------
# 时长预算：把「目标时长」换算成「分镜数」与「单镜旁白字数」
#
# 朗读语速口径与 media.estimate_duration 保持一致（中文约 4.4 字/秒）。
# 这两件事决定了「选 3 分钟就真的是 3 分钟」：
#   1) 分镜数随目标时长浮动，但始终落在设计要求的 8~12 之间；
#   2) 每镜旁白字数 = 目标秒数 ÷ 分镜数 × 语速。
# ----------------------------------------------------------------------
CHARS_PER_SECOND = 4.4
MIN_SHOTS, MAX_SHOTS = 8, 12
#: 单镜「舒适时长」：超过它就说明这一镜讲太满，短于它就说明太单薄
COMFORT_SECONDS_PER_SHOT = 20.0


def plan_shot_count(target_sec: float) -> int:
    """按目标时长决定分镜数：短课少镜、长课多镜，但夹在 8~12 之间"""
    n = int(round(max(60.0, target_sec) / COMFORT_SECONDS_PER_SHOT))
    return max(MIN_SHOTS, min(MAX_SHOTS, n))


def narration_budget(target_sec: float, n_shots: int) -> tuple[int, int]:
    """算出单镜旁白的「字数区间」(下限, 上限)，给 ±18% 余量便于断句"""
    per_sec = max(8.0, max(60.0, target_sec) / max(1, n_shots))
    mid = per_sec * CHARS_PER_SECOND
    lo = max(26, int(mid * 0.82))
    return lo, max(lo + 14, int(mid * 1.18))


def bullets_per_shot(target_sec: float, n_shots: int) -> int:
    """一屏放几条要点才不至于讲超时（每条要点连标题带说明约 30 字）"""
    lo, hi = narration_budget(target_sec, n_shots)
    return max(2, min(5, int(round(((lo + hi) / 2.0) / 30.0))))


#: 超长时可整段删掉的分镜，越靠前越先被删（这是「增补型」内容，不是教学主线）
_DROPPABLE = ("案例透视", "实践建议", "应用场景", "常见误区", "核心要素",
              "运作机制", "为什么重要")


def trim_shots(shots: list[dict], want: int) -> list[dict]:
    """分镜过多时按「可删优先级」整段删除，并保持 8~12 的边界与序号连续。

    只删整段、不截断句子 —— 这样「屏上要点」与「旁白」永远一一对应。
    """
    keep = list(shots)
    for scene in _DROPPABLE:
        if len(keep) <= max(MIN_SHOTS, want):
            break
        dropped = [s for s in keep if s["scene"] == scene]
        if dropped and len(keep) - len(dropped) >= MIN_SHOTS:
            keep = [s for s in keep if s["scene"] != scene]
    for i, s in enumerate(keep):
        s["index"] = i + 1
    return keep


def fit_narration_to_target(shots: list[dict], target_sec: float,
                            tolerance: float = 1.12) -> list[dict]:
    """兜底校准：总时长仍超出目标 12% 以上时，从最长的一镜开始按句裁掉末句。

    正常路径下旁白是「按预算写的」，走不到这里；这一步是为了让
    「目标时长」在极端情况（大模型不听话、文档内容特别长）下依然算数。
    """
    limit = max(30.0, target_sec) * tolerance

    def total() -> float:
        return sum(s.get("seconds") or 0 for s in shots)

    for _ in range(max(4, len(shots) * 3)):
        if total() <= limit:
            break
        longest = max(shots, key=lambda s: s.get("seconds") or 0)
        if (longest.get("seconds") or 0) <= 9.0:
            break
        text = longest.get("narration") or ""
        parts = [p for p in re.split(r"(?<=[。！？])", text) if p.strip()]
        if len(parts) <= 1:                     # 只剩一句，宁可略超也不切碎
            break
        longest["narration"] = "".join(parts[:-1])
        longest["seconds"] = estimate_duration(longest["narration"])
    return shots


# 句首编号：一、 / （2） / 3. 等
_HEADING_RE = re.compile(
    r"^[（(【\[]?\s*(?:[一二三四五六七八九十百]{1,3}|\d{1,2})\s*"
    r"(?:[）)】\]]|[、.．,，])\s*")
_DUP_PUNCT_RE = re.compile(r"([，。；：、])\1+")


def _tidy(s: str) -> str:
    """去掉句首编号、合并重复标点、清理首尾标点"""
    s = _HEADING_RE.sub("", (s or "").strip())
    s = _DUP_PUNCT_RE.sub(r"\1", s)
    s = re.sub(r"[。]\s*[，、；]", "，", s)
    return s.strip(" ，、,;；:：。.")


def _split_label(sentence: str) -> tuple[str, str]:
    """把句子拆成「短标题 | 说明」用于要点卡片；拆不开则返回 ('', 原句)"""
    s = _tidy(sentence)
    m = re.match(r"^(.{2,14}?)[，、：；]", s)
    if m:
        head, rest = m.group(1), s[m.end():].strip(" ，、；")
        if len(rest) >= 8:
            return head, rest
    return "", s


def _bullets(sentences: list[str]) -> list[str]:
    """把句子列表转成要点卡片数据"""
    out = []
    for s in sentences:
        head, rest = _split_label(s)
        out.append(f"{head}|{rest}" if head else rest)
    return out


def extract_keywords(text: str, topk: int = 12) -> list[str]:
    """抽取中文关键词：2~4 字词频 + 英文术语，去停用词"""
    text = _clean(text)
    if not text:
        return []
    counts: Counter = Counter()

    # 英文/数字术语（ADDIE、MOOC、GPT-4）
    for w in re.findall(r"[A-Za-z][A-Za-z0-9\-]{1,19}", text):
        if len(w) >= 2:
            counts[w] += 3

    # 中文 n-gram（按 2/3/4 字切，统计后做去重：长词优先）
    zh = re.sub(r"[^\u4e00-\u9fff]+", " ", text)
    for seg in zh.split():
        for n in (4, 3, 2):
            for i in range(len(seg) - n + 1):
                gram = seg[i:i + n]
                if gram in _STOP or any(ch in _STOP for ch in gram):
                    continue
                counts[gram] += {4: 3, 3: 2, 2: 1}[n]

    ranked = [w for w, _ in counts.most_common(topk * 4)]
    picked: list[str] = []
    for w in ranked:
        if any(w in p and w != p for p in picked):     # 去掉被长词包含的短词
            continue
        picked.append(w)
        if len(picked) >= topk:
            break
    return picked


def extract_sentences(text: str, min_len: int = 14, max_len: int = 90) -> list[str]:
    """切分为长度适中的句子。

    两个关键处理：
    · 保留换行作为切分边界 —— 否则「二、核心做法」会被拼进正文，
      读出来就成了「先给它一个清晰的定义。二、核心做法 把知识……」
    · 整行很短且没有任何句末标点时，判定为标题/文档名，直接跳过
    """
    out = []
    for line in _norm(text).split("\n"):
        line = line.strip()
        if not line:
            continue
        parts = re.split(r"[。！？；]", line)
        if len(parts) == 1 and len(line) <= 32:      # 标题行
            continue
        for s in parts:
            s = _tidy(s)
            if min_len <= len(s) <= max_len:
                out.append(s + "。")
    return out


def rank_sentences(text: str, topk: int = 8) -> list[str]:
    """按关键词覆盖度给句子打分，挑出最能代表文档的句子"""
    sents = extract_sentences(text)
    if not sents:
        return []
    kws = extract_keywords(text, topk=18)
    scored = []
    for i, s in enumerate(sents):
        score = sum(2.0 for k in kws if k in s)
        score += 1.0 / (1 + i * 0.05)          # 靠前的句子略优
        score += min(len(s), 60) / 200.0
        scored.append((score, i, s))
    scored.sort(key=lambda x: -x[0])
    picked = sorted(scored[:topk], key=lambda x: x[1])
    return [s for _, _, s in picked]


# ----------------------------------------------------------------------
# 领域词库：未命中精编骨架时，用领域术语把内容「撑」得有血有肉
# ----------------------------------------------------------------------
_DOMAINS = [
    {
        "name": "人工智能与教育技术",
        "match": ["ai", "人工智能", "生成式", "大模型", "大语言", "智能", "算法",
                  "机器学习", "chatgpt", "gpt", "提示词", "prompt", "数字化"],
        "subject": "教育技术",
        "concepts": ["技术能力强弱", "人机协同方式", "教师的主导作用", "数据与伦理边界"],
        "mechanism": [
            ("输入", "教师提供教学目标、学情与素材，明确任务边界"),
            ("生成", "模型基于大规模语料生成教案、试题、讲解与多媒体草案"),
            ("筛选", "教师依据学科逻辑与育人目标筛选、改写、补充"),
            ("反馈", "以学习数据与课堂表现为依据，持续迭代教学方案"),
        ],
        "applications": [
            "备课增效|自动生成教案初稿、课件框架与分层练习，把时间还给学情分析",
            "课堂互动|生成追问链与即时案例，支撑探究式、项目式学习",
            "个性化辅导|依据学情数据生成差异化任务与反馈，缓解大班教学矛盾",
            "教学评价|辅助设计量规、批量初评作业，教师专注高阶判断",
        ],
        "myths": [
            ("AI 可以替代教师完成教学|技术承担重复性劳动，育人与价值引导仍属教师"),
            ("生成内容可以直接使用|必须经学科审核与二次加工，核对事实与价值取向"),
            ("用了 AI 课堂就会变好|教学法先行、技术为辅，脱离目标的技术只会增加负担"),
            ("学生用了就是作弊|关键是重新设计任务与评价方式，培养批判性使用能力"),
        ],
        "tips": [
            ("目标先行|先写清学习目标与评价标准，再让技术介入"),
            ("小步试点|选一个教学环节先试用，跑通后再逐步扩展"),
            ("留痕可查|保留生成与修改记录，便于反思与教研共享"),
            ("伦理合规|注意数据隐私、学术诚信与内容版权边界"),
        ],
        "cases": [
            "某高校课程团队用大模型生成 30 个课堂追问，教师按认知层次筛选后使用",
            "教师在备课时用 AI 生成三层难度练习，再依据学情数据调整投放比例",
        ],
    },
    {
        "name": "课程与教学设计",
        "match": ["教学", "课堂", "课程", "设计", "目标", "评价", "学情", "教改",
                  "教研", "培养", "大纲", "学习", "素养", "翻转", "混合"],
        "subject": "教学设计与课程改革",
        "concepts": ["学习目标的可测性", "教学活动与目标的对应", "评价方式的匹配度", "学情起点与差异"],
        "mechanism": [
            ("分析", "明确学习需要、学习者特征与真实教学问题"),
            ("设计", "把目标拆成可观测的行为动词，设计达成路径"),
            ("开发", "准备内容、活动、资源与评价工具"),
            ("实施", "在课堂中组织学习，收集过程性证据"),
            ("评价", "依据证据判断达成度，反哺下一轮设计"),
        ],
        "applications": [
            "目标撰写|用可观测行为动词表述目标，避免「了解、掌握」这类模糊表述",
            "活动设计|每个活动都对应一条目标，删掉只热闹不达标的活动",
            "评价设计|评价任务与目标一一对齐，让学生知道「做到什么算好」",
            "学情诊断|用前置测或访谈找准起点，减少无效重复与盲目拔高",
        ],
        "myths": [
            ("内容讲完就算完成教学|学生学会才算完成，目标应指向学习结果"),
            ("活动越多课堂越丰富|活动要服务于目标，冗余活动会稀释学习时间"),
            ("评价就是期末考试|评价应贯穿过程，为改进教学提供证据"),
            ("改革就是推翻重来|教学改革是渐进优化，保留有效经验再迭代"),
        ],
        "tips": [
            ("逆向设计|先定评价证据，再设计教学活动"),
            ("目标对齐|目标—活动—评价三者逐条对应，制作一张对齐表"),
            ("证据意识|每一节课都留下可分析的学习证据"),
            ("持续迭代|把课堂反思写成下一轮的设计输入"),
        ],
        "cases": [
            "某课程把「了解」类目标改写为可观测行为后，作业与评价的一致性明显提升",
            "教研组用对齐表重构单元设计，删减了三成低效活动",
        ],
    },
    {
        "name": "学习方法与认知科学",
        "match": ["学习", "记忆", "认知", "思维", "迁移", "动机", "注意", "负荷",
                  "元认知", "策略", "考试", "复习"],
        "subject": "学习科学",
        "concepts": ["工作记忆容量有限", "长时记忆依靠意义编码", "迁移依赖多样化练习", "动机影响投入强度"],
        "mechanism": [
            ("注意", "信息进入工作记忆，容量极其有限，一次只能处理少数要素"),
            ("编码", "与已有知识建立联系，形成有意义的组块"),
            ("巩固", "通过间隔与提取练习把知识固化到长时记忆"),
            ("迁移", "在变化的情境中反复调用，形成可迁移的能力"),
        ],
        "applications": [
            "提取练习|用回忆、自测替代重复阅读，学习效率显著提升",
            "间隔安排|把集中复习拆成多次间隔，对抗遗忘曲线",
            "交错学习|混合不同类型问题，训练辨别与选择策略",
            "认知减负|减少无关装饰，让注意力集中在关键信息上",
        ],
        "myths": [
            ("反复阅读就能记住|阅读带来熟悉感，提取练习才带来真正的记忆"),
            ("学得快等于学得好|短期表现好可能是无效策略，长期保持才是标准"),
            ("按学习风格教学更有效|学习风格匹配说缺乏可靠证据支持"),
            ("越努力效果越好|努力要投在有效策略上，否则只是低效重复"),
        ],
        "tips": [
            ("低风险自测|频繁小测，错了不扣分，重点是暴露盲区"),
            ("间隔复习|把复习分散到多天，而不是考前突击"),
            ("变换情境|同一个知识在不同题目与场景中反复使用"),
            ("监控理解|合上书用自己的话复述，检验是否真的理解"),
        ],
        "cases": [
            "实验显示，同时间内用自测代替重读，一周后的保持率明显更高",
            "交错的练习安排让学生在遇到混合题型时更会辨别策略",
        ],
    },
]

_GENERIC_FALLBACK = {
    "subject": "通识讲解",
    "concepts": ["核心内涵", "关键构成", "适用条件", "边界与限制"],
    "mechanism": [
        ("背景", "先看它从什么现实问题里长出来"),
        ("内涵", "再看它的核心含义与关键特征"),
        ("结构", "拆开它的构成要素与相互关系"),
        ("应用", "最后看它在实践中怎么用、用在哪"),
    ],
    "applications": [
        "理解层面|建立清晰的概念框架，能用自己的话准确表述",
        "实践层面|知道在什么场景下该用它，以及第一步做什么",
        "反思层面|能识别它的局限，不盲目套用",
        "迁移层面|能把它与已有经验联结，形成可复用的方法",
    ],
    "myths": [
        ("概念会背就等于学会|理解要看能否在新情境中正确使用"),
        ("适用所有场景|每个概念都有前提条件与边界"),
        ("越复杂越高级|能简化并抓住本质才是真正掌握"),
        ("记住了就不用再想|需要在实践中反复检验与修正"),
    ],
    "tips": [
        ("先框架后细节|先建立整体结构，再填充具体知识"),
        ("用例子检验|用一个正例和一个反例检验理解"),
        ("讲给别人听|能讲清楚是检验理解的最快方式"),
        ("在实践中修正|把理解放到真实任务里检验"),
    ],
    "cases": [
        "把抽象概念放在一个真实案例里，理解速度会明显加快",
        "用反例对照，能迅速暴露理解中的模糊地带",
    ],
}


def _match_domain(topic: str, text: str = "") -> dict:
    hay = (topic + " " + text[:1500]).lower()
    best, best_hit = None, 0
    for dom in _DOMAINS:
        hit = sum(1 for k in dom["match"] if k in hay)
        if hit > best_hit:
            best, best_hit = dom, hit
    return best or _GENERIC_FALLBACK


# ----------------------------------------------------------------------
# 精编知识骨架（命中即用，内容质量最高）
# ----------------------------------------------------------------------
CURATED: dict[str, dict] = {
    "生成式ai如何赋能教学设计": {
        "title": "生成式AI如何赋能教学设计",
        "subject": "教育技术 · 教学设计",
        "hook": "如果一个工具能在三分钟内写出一份教案初稿，教师的时间应该花到哪里去？这是生成式AI进入课堂后，每一位教师都必须回答的问题。",
        "definition": "生成式AI赋能教学设计，指教师把重复性的内容生成工作交给技术，把专业判断与育人设计留给自己，形成人机协同的教学设计新流程。",
        "why": [
            "备课劳动强度大|教案、习题、课件占据了教师大量重复性时间",
            "学情差异显著|大班教学中统一内容难以兼顾不同起点的学生",
            "技术已足够可用|生成质量足以支撑初稿，人的加工成本大幅降低",
            "关键在教学设计|技术只解决效率，教学有效性仍取决于设计质量",
        ],
        "core": [
            "目标先行|先写清学习目标与评价标准，技术介入才有方向",
            "人机分工|机器负责生成与穷举，教师负责判断、取舍与育人",
            "证据驱动|用学习数据检验设计效果，而不是凭感觉判断",
            "伦理边界|数据隐私、学术诚信与内容准确性需要明确规则",
        ],
        "cases": [
            "教案初稿生成|依据教学目标与学生基础，生成结构化教案草案，教师二次加工",
            "分层练习设计|按认知层次生成三层难度任务，依据学情数据投放",
            "课堂提问链|生成由浅入深的追问序列，支撑探究式课堂",
            "评价量规辅助|生成评价维度草案，教师据此调整权重与描述语",
        ],
        "tips": [
            "写清约束再提问|把学情、课时、目标写进提示词，生成结果才可用",
            "先审核后使用|核对事实性内容与价值取向，这一步不能省",
            "保留修改痕迹|记录生成与修改过程，成为教研与反思的素材",
            "小步试点|先在一个环节试用，跑通后再扩展",
        ],
        "summary": [
            "生成式AI改变的是效率，不是教学规律",
            "教师的核心价值在于判断、设计与育人",
            "技术必须先服务于明确的学习目标",
            "人机协同的关键是清晰的边界与审慎的审核",
        ],
        "ending": "生成式AI不会替代教师，但会重新定义教师的时间分配。把重复劳动交给技术，把专业判断留给自己。",
    },
    "布鲁姆教育目标分类学": {
        "title": "布鲁姆教育目标分类学",
        "subject": "教育心理学 · 教学设计",
        "hook": "同一节课，为什么有的问题学生立刻能答，有的问题却让整个教室安静下来？布鲁姆给了我们一把衡量思维层次的尺子。",
        "definition": "布鲁姆教育目标分类学，把认知领域的学习目标由低到高分为记忆、理解、应用、分析、评价、创造六个层次，是教学设计中最经典的目标分析工具。",
        "why": [
            "目标模糊|「了解、掌握」难以观察，也无法评价达成度",
            "层次单一|大量课堂提问停留在记忆层，高阶思维训练不足",
            "评价错位|目标指向创造，评价却只考记忆",
            "可操作性强|六个层次提供了可观测的行为参照",
        ],
        "core": [
            "记忆|识别、回忆事实性信息，是后续学习的基础",
            "理解|用自己的话解释、举例、概括，形成意义",
            "应用|在新情境中执行或使用已学程序",
            "分析|把整体拆解为部分，理清要素之间的关系",
        ],
        "cases": [
            "设计目标|把「了解分类学」改写为「能区分六个层次并举例说明」",
            "设计提问|同一知识点设计六个层次的问题链，逐步提升思维难度",
            "设计作业|基础题对应应用层，开放题指向评价与创造层",
            "设计评价|用表现性任务考查高阶目标，而非仅用选择题",
        ],
        "tips": [
            "动词可观测|用可观察的动词描述目标，避免模糊表述",
            "目标—活动—评价对齐|三者逐条对应，形成一致性",
            "高阶不等于难|高阶是思维层次的提升，不是知识点更难",
            "层次不是台阶|真实学习中层次会往复交错，不必机械递进",
        ],
        "summary": [
            "六个层次：记忆、理解、应用、分析、评价、创造",
            "分类学的价值在于让目标可观察、可评价",
            "课堂提问的层次决定了思维训练的层次",
            "目标是教学设计的起点，也是评价的依据",
        ],
        "ending": "分类学不是用来给知识贴标签的，而是用来提醒我们：课堂的思维高度，取决于我们提出的问题高度。",
    },
    "什么是大语言模型": {
        "title": "什么是大语言模型",
        "subject": "人工智能通识",
        "hook": "当你输入一句话，它就能接着写下去——它到底是怎么做到的？理解这一点，才能真正理解今天的人工智能。",
        "definition": "大语言模型是通过海量文本训练出来的神经网络模型，核心能力是预测下一个词；正因为要准确预测，它被迫学会了语法、语义与部分世界知识。",
        "why": [
            "无处不在|搜索、翻译、写作、编程都在被它重塑",
            "理解即能力|会用与懂得用，取决于是否理解其原理与局限",
            "教育影响深远|教与学的方式、评价标准都在随之调整",
            "局限必须知道|它会一本正经地出错，也会受训练数据偏见影响",
        ],
        "core": [
            "规模|参数与训练数据规模极大，才涌现出通用语言能力",
            "预测机制|以「下一个词」为目标反复训练，学到语言规律",
            "注意力机制|让模型在处理一个词时参考上下文中相关的词",
            "局限|没有真实理解与事实核查能力，输出需人工验证",
        ],
        "cases": [
            "教学助手|生成教案初稿、讲解材料与分层练习",
            "语言陪练|模拟对话场景，提供即时反馈与纠错",
            "创作伙伴|辅助构思、改写与结构梳理，激发学生表达",
            "科研辅助|文献信息提取与要点归纳，但仍需人工核对",
        ],
        "tips": [
            "提供上下文|把背景、对象、目标写清楚，输出质量差异巨大",
            "要求分步|让模型先说思路再给结论，便于检查推理",
            "交叉验证|关键事实务必用可靠来源二次核对",
            "标注使用|在教学与科研中如实说明 AI 的参与程度",
        ],
        "summary": [
            "大语言模型的核心机制是预测下一个词",
            "能力来自规模与训练数据，而非真实理解",
            "会用它的前提是知道它会在哪里出错",
            "教育中的价值在于放大教师而非替代教师",
        ],
        "ending": "把大语言模型当成一位知识面极广、但从不主动承认无知的助手，你的使用方式就会立刻变得专业起来。",
    },
    "addie教学设计模型": {
        "title": "ADDIE 教学设计模型",
        "subject": "教学设计",
        "hook": "如果教学效果不理想，问题出在目标、内容、方法还是评价？ADDIE 给出的答案是：先别急着改内容，先回到系统。",
        "definition": "ADDIE 是分析、设计、开发、实施、评价五个阶段的系统化教学设计模型，强调以评价贯穿全程、以迭代推动改进。",
        "why": [
            "系统视角|避免只改局部，忽视目标与评价的一致性",
            "可复用|提供了通用流程，便于团队协作与质量把控",
            "以证据为中心|评价不是终点，而是下一轮设计的起点",
            "对教改友好|与课程建设、专业认证的改进逻辑天然契合",
        ],
        "core": [
            "分析|明确学习需要、学习者特征、现有问题与约束条件",
            "设计|撰写可测目标，规划内容序列、活动与评价方式",
            "开发|制作课件、案例、任务单与评价工具等教学资源",
            "实施|组织教学并收集过程性证据，及时调整",
        ],
        "cases": [
            "新开课程|从学情分析出发，先定评价标准再开发内容",
            "课程改造|用评价数据定位问题环节，避免全面推翻重来",
            "混合式教学|按阶段拆分线上线下任务，明确各环节目标",
            "项目式课程|先设计成果标准，再倒推任务与支持策略",
        ],
        "tips": [
            "多轮迭代|ADDIE 是循环而非直线，一次成型几乎不可能",
            "评价前置|在设计阶段就确定评价证据，避免事后补锅",
            "团队协同|不同阶段需要不同专长，明确分工与交接物",
            "留痕归档|每个阶段的决策记录是课程改进最宝贵的资产",
        ],
        "summary": [
            "五阶段：分析、设计、开发、实施、评价",
            "评价贯穿全程，而不是只在最后",
            "迭代是模型的常态，不是失败的表现",
            "核心追求是目标、活动与评价的一致性",
        ],
        "ending": "ADDIE 的价值不在于流程本身，而在于它强迫我们回答一个问题：这节课的问题，究竟出在哪一环？",
    },
    "翻转课堂": {
        "title": "翻转课堂：把课堂时间还给高阶思维",
        "subject": "教学模式改革",
        "hook": "如果学生在课前已经看完了讲解，那课堂上宝贵的时间应该用来做什么？翻转课堂给出的答案，是让课堂去做只有面对面才能做的事。",
        "definition": "翻转课堂是把知识传授环节前移到课前、把课堂时间用于答疑、讨论与高阶任务的一种教学模式，其本质是重新分配课堂时间与认知负荷。",
        "why": [
            "课堂时间稀缺|讲解占满课堂，学生缺少练习与反馈的机会",
            "差异难以照顾|统一讲授对快慢学生同时不友好",
            "技术条件成熟|微课与在线平台让课前学习成为可能",
            "提升参与度|课堂转向任务与讨论，学生投入度更高",
        ],
        "core": [
            "课前|以短小精悍的视频或阅读完成基础认知，配以检测任务",
            "课中|聚焦疑难、讨论与迁移应用，教师做诊断与引导",
            "课后|以项目或拓展任务巩固，形成完整学习闭环",
            "评价|过程性数据支撑个性化反馈，而不只看期末结果",
        ],
        "cases": [
            "课前微课|十分钟左右的短视频配合三道检测题，暴露预习盲区",
            "课堂研讨|基于课前数据分组讨论，教师针对共性问题集中讲解",
            "项目任务|用真实情境任务驱动知识应用，训练协作与表达",
            "同伴互评|用量规互评作品，学生从评价中学得更深",
        ],
        "tips": [
            "课前任务要轻|过长会劝退学生，宁短勿长并配检测",
            "课堂必须有变|如果课中仍以讲授为主，翻转就失效了",
            "评价要跟上|过程性数据是翻转课堂能否持续的关键",
            "先小范围试点|选一个班或一个单元试，降低改革风险",
        ],
        "summary": [
            "翻转的本质是重新分配课堂时间",
            "课前解决认知，课中解决思维与迁移",
            "没有评价配套，翻转很难持续",
            "先试点、再推广是稳妥路径",
        ],
        "ending": "翻转课堂真正翻转的不是视频和课堂，而是教师对课堂时间价值的判断。",
    },
    "核心素养导向的教学": {
        "title": "核心素养导向的教学",
        "subject": "课程改革",
        "hook": "学生毕业若干年后，忘掉知识点还剩下什么？这个问题的答案，就是素养。",
        "definition": "核心素养是学生应具备的、能够适应终身发展和社会发展需要的必备品格与关键能力，它指向在真实情境中解决问题的能力。",
        "why": [
            "超越知识本位|只教知识难以应对复杂真实问题",
            "评价方式变革|素养无法只靠纸笔测验测量",
            "育人目标明确|落实立德树人需要可操作的教学路径",
            "教师角色转变|从知识传递者转为学习设计者与引导者",
        ],
        "core": [
            "真实情境|在真实或拟真任务中运用知识，而非脱离情境的记忆",
            "单元设计|以大概念统领单元，形成结构化理解",
            "表现性评价|用量规评价过程与成果，关注证据",
            "反思迭代|引导学生自我监控与改进，形成元认知能力",
        ],
        "cases": [
            "大单元教学|用一个真实问题统领单元，串联知识、方法与价值",
            "表现性任务|设计需要综合运用知识才能完成的成果任务",
            "量规评价|提前公开评价标准，让学生明确「做到什么算好」",
            "跨学科项目|多学科协同解决复杂问题，培养综合能力",
        ],
        "tips": [
            "先找大概念|用少量核心概念组织大量内容",
            "任务要真实|越贴近真实情境，迁移价值越高",
            "标准要公开|量规提前给学生，评价才能促进学习",
            "证据要多样|作品、过程、反思都可以是素养证据",
        ],
        "summary": [
            "素养指向真实情境中的问题解决能力",
            "大概念与单元设计是落地的主要路径",
            "表现性评价是素养评价的核心方式",
            "评价标准公开才能促进学生学习",
        ],
        "ending": "素养不是额外增加的教学内容，而是重新回答了一个问题：我们希望学生带着什么走出这门课。",
    },
}

_ALIASES = {
    "生成式ai如何赋能教学设计": ["生成式ai", "aigc", "ai赋能", "人工智能赋能教学", "ai教学设计", "生成式人工智能"],
    "布鲁姆教育目标分类学": ["布鲁姆", "bloom", "教育目标分类", "认知层次", "六个层次"],
    "什么是大语言模型": ["大语言模型", "llm", "大模型", "语言模型"],
    "addie教学设计模型": ["addie", "教学设计模型"],
    "翻转课堂": ["翻转课堂", "flipped"],
    "核心素养导向的教学": ["核心素养", "素养导向", "大单元", "单元教学"],
}


def _match_curated(topic: str) -> dict | None:
    key = re.sub(r"[\s_\-·，。,.!?？:：;；\"'“”（）()\[\]【】]", "", topic).lower()
    if not key:
        return None
    if key in CURATED:
        return CURATED[key]
    for ckey, aliases in _ALIASES.items():
        for a in aliases:
            if a in key and ckey in CURATED:
                return CURATED[ckey]
    for ckey, entry in CURATED.items():
        a = re.sub(r"[\s_\-·]", "", ckey)
        if a in key or key in a:
            return entry
    return None


# ----------------------------------------------------------------------
# 分镜装配
# ----------------------------------------------------------------------
def _shot(layout: str, scene: str, title: str, bullets: list[str],
          narration: str, **extra) -> dict:
    shot = {
        "scene": scene,
        "layout": layout,
        "title": title,
        "bullets": bullets,
        "narration": narration,
        "seconds": estimate_duration(narration),
    }
    shot.update(extra)
    return shot


def _build_from_fields(topic: str, f: dict, audience: str, target_sec: float,
                       style: str) -> dict:
    """把「内容字段」装配成 8~12 个分镜

    target_sec 不再只是一个摆设：它决定分镜数（8~12 之间浮动）与
    每屏要点条数，从而让「目标时长」选多少就出多少。
    """
    shots: list[dict] = []
    n_want = plan_shot_count(target_sec)
    cap = bullets_per_shot(target_sec, n_want)      # 每屏要点上限
    cap_case = max(2, cap - 1)                      # 案例文字长，少放一条
    cap_sum = min(5, cap + 1)                       # 回顾屏是在总结，可略多

    shots.append(_shot(
        "cover", "封面", f.get("title") or topic, [],
        f"大家好。这节课我们来聊一个话题：{f.get('title') or topic}。"
        f"我会用大约{(f.get('_minutes') or 4):.0f}分钟，把它讲清楚、讲透。",
        subtitle="", meta=f"面向{audience}", visual_kind="motif"))

    shots.append(_shot(
        "quote", "问题引入", "先从一个问题说起", [f["hook"]],
        f["hook"], visual_kind="spotlight"))

    shots.append(_shot(
        "quote", "概念界定", "它到底是什么", [f["definition"]],
        f"先给它一个清晰的定义。{f['definition']}", visual_kind="spotlight"))

    def pair(b) -> tuple[str, str]:
        """'短标题|说明' → ('短标题', '说明')；并清理首尾标点"""
        h, _, d = str(b).partition("|")
        return _tidy(h), _tidy(d)

    def say(items: list, leads: list[str]) -> str:
        """把要点列表说成一段连贯的话（同时避免出现「。。」这种重复标点）"""
        parts = []
        for i, it in enumerate(items):
            h, d = pair(it)
            lead = leads[i] if i < len(leads) else ""
            parts.append(f"{lead}{h}，{d}。" if d else f"{lead}{h}。")
        return "".join(parts)

    ORD = ["第一，", "第二，", "第三，", "第四，", "第五，"]
    STEP = ["第一步，", "第二步，", "第三步，", "第四步，", "第五步，"]
    BLANK = [""] * 5
    # 文档驱动时，过渡句要中性一些：文档里的句子未必严格对应「为什么/怎么用」，
    # 用「材料强调了几点」这类说法才不会出现语义错位。
    doc = bool(f.get("_doc"))

    why = [b for b in f.get("why", [])][:cap]
    if why:
        shots.append(_shot(
            "points", "为什么重要", "为什么值得关注", why,
            ("材料为什么要讨论这个问题？主要有这么几点。" if doc
             else "为什么它值得关注？主要有这么几点。") + say(why, ORD) +
            "理解了这几点，我们再往下拆解它的内部结构。",
            visual_kind="rail"))

    core = [b for b in f.get("core", [])][:cap]
    if core:
        shots.append(_shot(
            "board", "核心要素", "拆开来看，它由这几部分组成", core,
            visual_kind="concept",
            narration=("材料接下来拆解了几个关键部分。" if doc
                       else "把概念拆开，它包含几个关键部分。") + say(core, BLANK) +
                      "这几个部分不是并列的清单，而是相互支撑的整体。"))

    mechanism = [f"{a}|{b}" for a, b in f.get("mechanism", [])][:cap]
    if mechanism:
        shots.append(_shot(
            "board", "运作机制", "它是怎么运转起来的", mechanism,
            "那么它是如何运转的？可以分成几个依次推进的环节。" +
            say(mechanism, STEP) + "这条链路走通，整个机制就成立了。",
            visual_kind="flow"))

    apps = [b for b in f.get("applications", [])][:cap]
    if apps:
        shots.append(_shot(
            "board", "应用场景", "在实践中怎么用", apps,
            ("材料还给出了几个可以落地的地方。" if doc
             else "落到实践中，它主要体现在这样几个方面。") + say(apps, BLANK),
            visual_kind="tags"))

    cases = [b for b in f.get("cases", [])][:cap_case]
    if cases:
        shots.append(_shot(
            "board", "案例透视", "看几个具体的场景", cases,
            "我们来看几个具体的场景。" +
            "".join((f"{pair(c)[0]}：{pair(c)[1]}。" if pair(c)[1] else f"{pair(c)[0]}。")
                    for c in cases) +
            "这些做法的共同点是，都从明确的教学问题出发，而不是从技术出发。",
            visual_kind="tags"))

    myths = [b for b in f.get("myths", [])][:cap]
    if myths:
        shots.append(_shot(
            "compare", "常见误区", "这些误解需要澄清", myths,
            "在实践中有几种常见的误解需要澄清。" +
            "".join((f"有人认为{pair(m)[0]}，但实际上是{pair(m)[1]}。"
                     if pair(m)[1] else f"有人认为{pair(m)[0]}。")
                    for m in myths[:3]),
            visual_kind="compare"))

    tips = [b for b in f.get("tips", [])][:cap]
    if tips:
        shots.append(_shot(
            "steps", "实践建议", "给你的几条可操作建议", tips,
            "最后给你几条可以直接上手的建议。" +
            "".join((f"{pair(t)[0]}——{pair(t)[1]}。" if pair(t)[1] else f"{pair(t)[0]}。")
                    for t in tips), visual_kind="check"))

    summary = [b for b in f.get("summary", [])][:cap_sum]
    shots.append(_shot(
        "summary", "要点回顾", "这节课我们讲了什么", summary,
        "我们来回顾一下今天的内容。" + "".join(f"{_tidy(s)}。" for s in summary) +
        "如果只记一句话，请记住这一句。", visual_kind="mind"))

    shots.append(_shot(
        "ending", "片尾", "谢谢观看", summary[:3],
        f.get("ending") or f"{topic}的核心，在于理解它的边界，并在实践中不断检验。感谢观看。",
        visual_kind="motif"))

    shots = trim_shots(shots, n_want)               # 超出的增补型分镜整段去掉
    for i, s in enumerate(shots):
        s["index"] = i + 1
    return {
        "title": f.get("title") or topic,
        "subject": f.get("subject", ""),
        "audience": audience,
        "style": style,
        "shots": shots,
        "outline": [{"heading": s["scene"], "points": s["bullets"]} for s in shots],
    }


# ----------------------------------------------------------------------
# 文档驱动：从上传文档生成内容字段
# ----------------------------------------------------------------------
def _fields_from_document(topic: str, text: str) -> dict:
    keywords = extract_keywords(text, topk=10)
    sents = rank_sentences(text, topk=16)
    dom = _match_domain(topic, text)

    def pick(a: int, b: int) -> list[str]:
        return sents[a:b]

    f = {
        "title": topic or "文档精讲",
        "subject": dom["subject"] + " · 文档精讲",
        "_doc": True,
        "hook": (f"这份材料围绕「{topic}」展开。{sents[0]}" if sents
                 else f"我们围绕「{topic}」展开讲解。"),
        "definition": (sents[1] if len(sents) > 1
                       else f"{topic}是材料中反复强调的核心内容。"),
        "why": _bullets(pick(2, 6)) or _bullets(pick(0, 4)) or
               ["材料要点|文档中给出了相关说明"],
        "core": _bullets(pick(6, 10)) or _bullets(pick(0, 4)) or
                ["核心内容|文档中的关键论述"],
        "mechanism": dom["mechanism"],
        "applications": _bullets(pick(10, 14)) or dom["applications"],
        "cases": _bullets(pick(14, 16)) or dom["cases"],
        "myths": dom["myths"],
        "tips": dom["tips"],
        "summary": sents[:4] or [f"围绕{topic}的核心要点"],
        "ending": f"以上是「{topic}」材料的关键内容，建议对照原文再读一遍，效果更好。",
        "_keywords": keywords,
    }
    return f


# ----------------------------------------------------------------------
# 对外入口
# ----------------------------------------------------------------------
def build_fields(topic: str, source_text: str = "", audience: str = "本科生",
                 minutes: float = 4.0, style: str = "calm",
                 doc_name: str = "") -> tuple[dict, str]:
    """② 结构层的输入：得到「讲什么」（内容字段）与生成方式说明。

    两条路径：
      · 上传了文档（≥200 字）→ 文档驱动：提炼关键词与关键句
      · 未上传文档         → 主题驱动：命中精编骨架则用精编内容，否则通用叙事骨架
    """
    topic = _clean(topic) or "知识讲解"
    source_text = _norm(source_text)      # 保留换行，标题才不会串进正文

    if len(source_text) >= 200:
        fields = _fields_from_document(topic, source_text)
        return fields, f"文档驱动引擎（{doc_name or '上传文档'}）"

    curated = _match_curated(topic)
    if curated:
        f = dict(curated)
        # 精编骨架只写「最有把握」的字段，缺失的用同领域通用内容补齐，
        # 这样每个主题都能稳定产出 8~12 个分镜（对应设计图的分镜数要求）。
        dom = _match_domain(topic)
        for key in ("applications", "myths", "cases", "tips"):
            if not f.get(key):
                f[key] = dom[key]
        return f, "内置教学脚本引擎 · 精编骨架"

    dom = _match_domain(topic)
    kws = extract_keywords(topic, topk=5) or [topic]
    fields = {
        "title": topic,
        "subject": dom["subject"],
        "hook": f"当我们说「{topic}」时，我们到底在说什么？先把这个问题讲清楚，后面的内容才站得住。",
        "definition": f"{topic}，是指在特定条件下，围绕{('、'.join(kws[:3]))}展开的一套相对稳定的认识与实践方式。"
                      f"理解它的关键，是抓住它要解决的真实问题。",
        "why": [f"现实需要|它回应的是{dom['name']}实践中反复出现的真实问题"] +
               [f"{c}|这是判断是否真正理解{topic}的关键分界线" for c in dom["concepts"][:3]],
        "core": [f"{c}|围绕{c}展开，才能避免理解停留在表面" for c in dom["concepts"]],
        "mechanism": dom["mechanism"],
        "applications": dom["applications"],
        "cases": dom["cases"],
        "myths": dom["myths"],
        "tips": dom["tips"],
        "summary": [f"{topic}指向的是真实问题的解决",
                    f"抓住{dom['concepts'][0]}等关键要素",
                    "在具体情境中检验理解，而非机械套用",
                    "明确它的边界与适用条件"],
        "ending": f"理解{topic}，重点不在记住定义，而在于遇到真实问题时，你能想起它、用得上它。感谢观看。",
        "_keywords": kws,
    }
    return fields, "内置教学脚本引擎 · 通用叙事骨架"


def plan_structure(topic: str, fields: dict, audience: str = "本科生",
                   minutes: float = 4.0, style: str = "calm") -> dict:
    """② 结构层的产物：分镜骨架（版式 + 要点），此时还没有旁白稿。"""
    full = _build_from_fields(topic, dict(fields), audience, max(60.0, minutes * 60.0), style)
    shots = []
    for s in full["shots"]:
        sk = {k: v for k, v in s.items() if k != "narration"}
        sk["seconds"] = 0.0
        shots.append(sk)
    return {
        "title": full["title"],
        "subject": full.get("subject", ""),
        "style": style,
        "audience": audience,
        "shots": shots,
        "outline": full["outline"],
    }


def write_narration(topic: str, fields: dict, shots: list[dict],
                    audience: str = "本科生", minutes: float = 4.0,
                    style: str = "calm") -> list[dict]:
    """③ 脚本层的产物：为骨架逐镜写旁白稿（与结构层同源，保证一一对应）。"""
    full = _build_from_fields(topic, dict(fields), audience, max(60.0, minutes * 60.0), style)
    narr = {s["index"]: s["narration"] for s in full["shots"]}
    out = []
    for s in shots:
        shot = dict(s)
        shot["narration"] = narr.get(shot.get("index"), "")
        shot["seconds"] = estimate_duration(shot["narration"])
        out.append(shot)
    return out


def _finish(plan: dict, fields: dict, topic: str, source: str) -> dict:
    shots = plan["shots"]
    plan["source"] = source
    plan["keywords"] = fields.get("_keywords") or extract_keywords(topic, topk=6)
    plan["minutes"] = round(sum(s["seconds"] for s in shots) / 60.0, 1)
    plan["script"] = "".join(s["narration"] for s in shots)
    return plan


def finalize(topic: str, fields: dict, structure: dict, shots: list[dict],
             source: str, audience: str = "本科生", minutes: float = 4.0) -> dict:
    """把「结构层骨架 + 脚本层旁白」合成最终方案，并做一次时长校准。

    校准是双向的：太短就补一句过渡，太长就按句裁掉，保证落点在目标时长附近。
    """
    total = sum(s.get("seconds", 0) for s in shots)
    if total < minutes * 60 * 0.62 and len(shots) > 1:
        shots[1]["narration"] += " 在开始之前，先说明一点：我们会从概念、结构、应用和误区四个层面依次展开。"
        shots[1]["seconds"] = estimate_duration(shots[1]["narration"])
    shots = fit_narration_to_target(shots, minutes * 60)
    plan = {
        "title": structure.get("title") or topic,
        "subject": structure.get("subject", ""),
        "audience": audience,
        "style": structure.get("style", "calm"),
        "shots": shots,
        "outline": [{"heading": s["scene"], "points": s.get("bullets", [])} for s in shots],
        "target_seconds": max(60.0, minutes * 60.0),
    }
    return _finish(plan, fields, topic, source)


# ----------------------------------------------------------------------
# 对外入口
# ----------------------------------------------------------------------
def build_plan(topic: str, source_text: str = "", audience: str = "本科生",
               minutes: float = 4.0, style: str = "calm",
               doc_name: str = "") -> dict:
    """一步到位生成完整分镜方案（②结构 + ③脚本）"""
    fields, source = build_fields(topic, source_text, audience, minutes, style, doc_name)
    fields["_minutes"] = minutes
    plan = _build_from_fields(_clean(topic) or "知识讲解", fields, audience,
                              max(60.0, minutes * 60.0), style)

    total = sum(s["seconds"] for s in plan["shots"])
    if total < minutes * 60 * 0.62:
        plan["shots"][1]["narration"] += " 在开始之前，先说明一点：我们会从概念、结构、应用和误区四个层面依次展开。"
        plan["shots"][1]["seconds"] = estimate_duration(plan["shots"][1]["narration"])
    plan["shots"] = fit_narration_to_target(plan["shots"], minutes * 60)
    return _finish(plan, fields, topic, source)


def assemble_from_fields(topic: str, fields: dict, audience: str = "本科生",
                         minutes: float = 4.0, style: str = "calm",
                         source: str = "大模型生成") -> dict:
    """把「内容字段」（可来自大模型）装配成标准分镜方案。

    与 build_plan 共用同一套装配逻辑，保证「有 Key / 无 Key」两条路径
    产出的数据结构完全一致。
    """
    fields = dict(fields or {})
    fields["_minutes"] = minutes
    plan = _build_from_fields(_clean(topic) or "知识讲解", fields, audience,
                              max(60.0, minutes * 60.0), style)
    plan["shots"] = fit_narration_to_target(plan["shots"], minutes * 60)
    return _finish(plan, fields, topic, source)

