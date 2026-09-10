# -*- coding: utf-8 -*-
"""文字排版工具：中文字体加载、按像素折行、自动缩字号。

抽成独立模块，是因为画面渲染（slides）和插图绘制（illustrate）都要用，
放在任一方里都会造成循环依赖。
"""
from __future__ import annotations

from PIL import Image, ImageDraw, ImageFont

from . import config

_MEASURE = ImageDraw.Draw(Image.new("RGB", (8, 8)))
_FONT_CACHE: dict = {}


def get_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """按字号取中文字体（找不到中文字体时退回默认字体，绝不抛异常）"""
    size = max(8, int(size))
    key = (size, bold)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    path = config.font_path(bold)
    try:
        font = ImageFont.truetype(path, size) if path else ImageFont.load_default()
    except Exception:
        font = ImageFont.load_default()
    _FONT_CACHE[key] = font
    return font


def text_w(text: str, font) -> float:
    try:
        return _MEASURE.textlength(text, font=font)
    except Exception:
        return len(str(text)) * getattr(font, "size", 16) * 0.9


def wrap(text: str, font, max_width: float) -> list[str]:
    """按像素宽度折行（中文逐字、支持手动换行）"""
    lines: list[str] = []
    for paragraph in str(text).split("\n"):
        cur = ""
        for ch in paragraph:
            trial = cur + ch
            if text_w(trial, font) <= max_width or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = ch
        lines.append(cur)
    return lines


def fit_text(text: str, max_width: float, max_lines: int,
             sizes: list[int], bold: bool = False) -> tuple[list[str], ImageFont.FreeTypeFont]:
    """自动缩字号，直到在 max_lines 行内放得下；实在放不下就省略号收尾"""
    for size in sizes:
        font = get_font(size, bold)
        lines = wrap(text, font, max_width)
        if len(lines) <= max_lines:
            return lines, font
    font = get_font(sizes[-1], bold)
    lines = wrap(text, font, max_width)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1][:-1] + "…"
    return lines, font


def ellipsis(text: str, font, max_width: float) -> str:
    text = str(text)
    if text_w(text, font) <= max_width:
        return text
    out = text
    while out and text_w(out + "…", font) > max_width:
        out = out[:-1]
    return out + "…"


def fit_one_line(text: str, font, max_width: float) -> str:
    return ellipsis(text, font, max_width)
