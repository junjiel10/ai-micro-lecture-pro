# -*- coding: utf-8 -*-
"""全局配置 · 妙课生花 WonderKourse

设计原则：
1. 零外部安装 —— 画面用 Pillow 直接渲染（不依赖 LibreOffice），
   ffmpeg 由 imageio-ffmpeg 提供（pip 安装，不需管理员权限）；
2. 无 API Key 也能跑 —— 脚本环节内置「教学脚本引擎」，
   配置 Key 后自动升级为大模型生成；
3. 中文 Windows 友好 —— 自动定位中文字体，控制台编码自动修正。
"""
import os
import sys

# ----------------------------------------------------------------------
# 路径
# ----------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)


# ----------------------------------------------------------------------
# .env 读取（不引入额外依赖）
# ----------------------------------------------------------------------
def load_env_file(path: str | None = None) -> None:
    """读取项目根目录的 .env，写入环境变量（已存在的环境变量优先）"""
    path = path or os.path.join(BASE_DIR, ".env")
    if not os.path.exists(path):
        return
    try:
        with open(path, encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key, val = key.strip(), val.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = val
    except Exception:
        pass


load_env_file()


def refresh() -> None:
    """重新读取环境变量（配置 Key 后无需重启进程）"""
    global LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, TTS_VOICE, TTS_RATE
    global ILLUSTRATIONS, IMAGE_API_KEY, IMAGE_BASE_URL, IMAGE_MODEL
    load_env_file()
    LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
    LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com/v1")
    LLM_MODEL = os.environ.get("LLM_MODEL", "deepseek-chat")
    TTS_VOICE = os.environ.get("TTS_VOICE", "zh-CN-YunxiNeural")
    TTS_RATE = os.environ.get("TTS_RATE", "+8%")
    ILLUSTRATIONS = os.environ.get("ILLUSTRATIONS", "1") not in ("0", "false", "False")
    IMAGE_API_KEY = os.environ.get("IMAGE_API_KEY", "")
    IMAGE_BASE_URL = os.environ.get("IMAGE_BASE_URL", "")
    IMAGE_MODEL = os.environ.get("IMAGE_MODEL", "")


# ----------------------------------------------------------------------
# 大模型（可选，留空则使用内置教学脚本引擎）
# ----------------------------------------------------------------------
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com/v1")
LLM_MODEL = os.environ.get("LLM_MODEL", "deepseek-chat")

# ----------------------------------------------------------------------
# 配音
# ----------------------------------------------------------------------
TTS_VOICE = os.environ.get("TTS_VOICE", "zh-CN-YunxiNeural")
TTS_RATE = os.environ.get("TTS_RATE", "+8%")
# 可选音色：zh-CN-XiaoxiaoNeural(女) / zh-CN-YunxiNeural(男) /
#          zh-CN-YunyangNeural(新闻男) / zh-CN-XiaoyiNeural(女)
TTS_ENGINES = ("edge", "sapi", "silent")   # 依次降级
BGM_ENABLED = os.environ.get("BGM_ENABLED", "1") not in ("0", "false", "False")
BGM_VOLUME = 0.10                          # 背景音乐相对音量

# ----------------------------------------------------------------------
# 视频 / 画面比例
# ----------------------------------------------------------------------
# 横版适合电脑、投影、B 站；竖版适合手机端（抖音 / 视频号 / 小红书）。
# 版式渲染会按 format 自适应：竖版把横向排列的流程、对比改成纵向堆叠。
FORMATS: dict[str, dict] = {
    "landscape": {
        "key": "landscape", "name": "横版 16:9", "desc": "1920×1080 · 电脑/投影",
        "w": 1920, "h": 1080, "margin": 130, "top": 190, "bottom": 170,
        "scale": 1.0, "gap": 26, "sub_font": 44, "sub_margin": 70,
    },
    "portrait": {
        "key": "portrait", "name": "竖版 9:16", "desc": "1080×1920 · 手机竖屏",
        "w": 1080, "h": 1920, "margin": 84, "top": 230, "bottom": 360,
        "scale": 0.86, "gap": 22, "sub_font": 52, "sub_margin": 260,
    },
}
DEFAULT_FORMAT = os.environ.get("VIDEO_FORMAT", "landscape")


def get_format(key: str | None = None) -> dict:
    """按 key 取画面格式，非法值回退到默认格式（横版）"""
    k = (key or "").lower()
    if k in FORMATS:
        return FORMATS[k]
    return FORMATS.get(DEFAULT_FORMAT, FORMATS["landscape"])


WIDTH, HEIGHT = FORMATS["landscape"]["w"], FORMATS["landscape"]["h"]  # 兼容旧引用
FPS = 25
VIDEO_CODEC = "libx264"
CRF = "20"
PRESET = "medium"
COVER_DURATION = 3.0      # 片头时长（秒）
ENDING_DURATION = 3.0     # 片尾时长（秒）
SHOT_GAP = 0.35           # 分镜之间的停顿（秒）

# ----------------------------------------------------------------------
# 插图
# ----------------------------------------------------------------------
# 1：按分镜语义自动生成「概念图 / 流程图 / 标签云 / 对比图」等结构化插图
# 0：只保留纯文字版式
ILLUSTRATIONS = os.environ.get("ILLUSTRATIONS", "1") not in ("0", "false", "False")

# 可选：外部「文生图」接口（OpenAI 兼容 /images/generations，如通义万相、智谱 CogView）
# 不配置时使用本地程序化插图（无需联网、无需 Key，永远可用）
IMAGE_API_KEY = os.environ.get("IMAGE_API_KEY", "")
IMAGE_BASE_URL = os.environ.get("IMAGE_BASE_URL", "")
IMAGE_MODEL = os.environ.get("IMAGE_MODEL", "")

# 字幕
# 字体族名不写死：libass 认的是「字体族名」而不是文件名，
# 得跟着本机实际找到的那个字体走（Windows 是微软雅黑，Linux 容器里是 Noto Sans CJK）。
# 见下方 subtitle_font_name()；仍可用环境变量 SUBTITLE_FONT_NAME 手动覆盖。
SUBTITLE_MARGIN_V = 70    # 距底部像素
SUBTITLE_FONT_SIZE = 44
SUBTITLE_MAX_CHARS = 20   # 单行最多字数（超过则拆行）
SUBTITLE_MAX_LINES = 2

# ----------------------------------------------------------------------
# 主题色（画面渲染用）
# ----------------------------------------------------------------------
THEMES = {
    "deepsea": {
        "name": "深海蓝",
        "bg_top": (18, 32, 62), "bg_bottom": (10, 18, 36),
        "accent": (94, 168, 255), "accent2": (124, 232, 200),
        "text": (240, 246, 255), "muted": (152, 170, 200),
        "card": (30, 48, 84),
    },
    "scholar": {
        "name": "书院青",
        "bg_top": (16, 48, 46), "bg_bottom": (8, 24, 24),
        "accent": (86, 214, 186), "accent2": (255, 206, 122),
        "text": (238, 250, 246), "muted": (148, 180, 172),
        "card": (24, 66, 62),
    },
    "sunrise": {
        "name": "晨光橙",
        "bg_top": (54, 30, 24), "bg_bottom": (24, 14, 12),
        "accent": (255, 152, 92), "accent2": (255, 214, 130),
        "text": (255, 246, 238), "muted": (198, 170, 156),
        "card": (74, 44, 34),
    },
}


def get_theme(name: str = "deepsea") -> dict:
    return THEMES.get(name) or THEMES["deepsea"]


# ----------------------------------------------------------------------
# 中文字体自动定位
# ----------------------------------------------------------------------
_FONT_CANDIDATES = {
    "regular": [
        r"C:\Windows\Fonts\msyh.ttc",          # 微软雅黑
        r"C:\Windows\Fonts\msyhl.ttc",
        r"C:\Windows\Fonts\simhei.ttf",        # 黑体
        r"C:\Windows\Fonts\Deng.ttf",          # 等线
        r"C:\Windows\Fonts\simsun.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    ],
    "bold": [
        r"C:\Windows\Fonts\msyhbd.ttc",        # 微软雅黑 Bold
        r"C:\Windows\Fonts\simhei.ttf",
        r"C:\Windows\Fonts\Dengb.ttf",
        "/System/Library/Fonts/PingFang.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    ],
}

_FONT_CACHE: dict = {}

# 字体文件名片段 → libass / fontconfig 认的字体族名
_FONT_FAMILY = (
    ("msyh", "Microsoft YaHei"),
    ("simhei", "SimHei"),
    ("simsun", "SimSun"),
    ("deng", "DengXian"),
    ("pingfang", "PingFang SC"),
    ("notosanscjk", "Noto Sans CJK SC"),
    ("notoserifcjk", "Noto Serif CJK SC"),
    ("wqy", "WenQuanYi Zen Hei"),
    ("sourcehansans", "Source Han Sans SC"),
)


def font_path(bold: bool = False) -> str | None:
    """返回可用的中文字体文件路径（找不到返回 None）"""
    key = "bold" if bold else "regular"
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    found = None
    for cand in _FONT_CANDIDATES[key] + _FONT_CANDIDATES["regular"]:
        if os.path.exists(cand):
            found = cand
            break
    _FONT_CACHE[key] = found
    return found


def subtitle_font_name() -> str:
    """字幕要用的字体族名（给 ffmpeg 的 libass 用）。

    画面上那些字是 Pillow 拿字体文件直接画的，而字幕是 ffmpeg 通过
    fontconfig 按「族名」找字体——两边机制不同，所以这里必须跟着
    font_path() 实际命中的那个文件走，不能写死。
    找不到时返回 sans-serif 交给系统兜底。
    """
    env = (os.environ.get("SUBTITLE_FONT_NAME") or "").strip()
    if env:
        return env
    low = (font_path(False) or "").lower()
    for frag, family in _FONT_FAMILY:
        if frag in low:
            return family
    return "sans-serif"


# ----------------------------------------------------------------------
# 控制台编码（中文 Windows 的 GBK 控制台会因 emoji/箭头报错）
# ----------------------------------------------------------------------
def fix_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


fix_console()
