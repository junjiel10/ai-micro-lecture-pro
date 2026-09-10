# -*- coding: utf-8 -*-
"""画面渲染层：用 Pillow 把分镜渲染成幻灯片图片（横版 16:9 / 竖版 9:16 自适应）。

为什么不用 python-pptx + LibreOffice？
  那套方案在 Windows 上要额外装 LibreOffice 与 poppler，还会踩字体/中文字形坑；
  直接用 Pillow 绘制，零外部依赖、版式可控、出图更快，且中文一定能显示。

版式（layout）：
  cover    片头：主题胶囊 + 大标题 + 装饰主视觉
  points   要点卡片（2–4 张，支持「小标题|说明」）
  steps    流程步骤（横版横排 / 竖版纵向流程链）
  compare  左右对比（横版双栏 / 竖版上下对照）
  quote    概念定调（居中大字）
  summary  要点回顾（编号列表）
  board    图文混排（左文右图 / 竖版上图下文）—— 配合 illustrate 的结构化插图
  ending   片尾
"""
from __future__ import annotations

import os

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from . import config
from . import illustrate
from . import textkit as tk


class SlideRenderer:
    """按指定画面格式渲染分镜幻灯片"""

    def __init__(self, fmt: str = "landscape", theme_name: str = "deepsea",
                 brand: str = "妙课生花 WonderKourse", subject: str = "", theme_key: str = "calm"):
        self.fmt = config.get_format(fmt)
        self.W: int = self.fmt["w"]
        self.H: int = self.fmt["h"]
        self.M: int = self.fmt["margin"]       # 左右安全边距
        self.TOP: int = self.fmt["top"]        # 内容区顶部
        self.BOTTOM: int = self.fmt["bottom"]  # 内容区底部（给字幕/进度条留白）
        self.S: float = self.fmt["scale"]      # 字号缩放
        self.portrait: bool = self.H > self.W

        self.theme = config.get_theme(theme_name)
        self.brand = brand
        self.subject = subject
        self.theme_key = theme_key
        self.artist = illustrate.Artist(self.theme, (self.W, self.H), self.S)

    # ------------------------------------------------------------------
    # 基础工具
    # ------------------------------------------------------------------
    def f(self, size: float, bold: bool = False):
        return tk.get_font(size * self.S, bold)

    def _rgba(self, c, a: int):
        return (c[0], c[1], c[2], int(a))

    def _gradient(self) -> Image.Image:
        top = np.array(self.theme["bg_top"], dtype=np.float32)
        bottom = np.array(self.theme["bg_bottom"], dtype=np.float32)
        ys = np.linspace(0, 1, self.H, dtype=np.float32)[:, None]
        xs = np.linspace(0, 1, self.W, dtype=np.float32)[None, :]
        t = np.clip(ys * 0.72 + xs * 0.28, 0, 1)[:, :, None]
        arr = top[None, None, :] * (1 - t) + bottom[None, None, :] * t
        return Image.fromarray(arr.astype(np.uint8), "RGB")

    def _glow(self, base: Image.Image, center, radius: int, color, alpha: int,
              blur: int = 160) -> Image.Image:
        layer = Image.new("RGBA", (self.W, self.H), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        cx, cy = center
        d.ellipse([cx - radius, cy - radius, cx + radius, cy + radius],
                  fill=self._rgba(color, alpha))
        return Image.alpha_composite(base.convert("RGBA"),
                                     layer.filter(ImageFilter.GaussianBlur(blur)))

    def _canvas(self) -> Image.Image:
        img = self._gradient()
        img = self._glow(img, (-int(self.W * 0.08), self.H + 120), int(self.W * 0.28),
                         self.theme["accent"], 46, blur=int(self.W * 0.10))
        img = self._glow(img, (self.W + 120, -120), int(self.W * 0.24),
                         self.theme["accent2"], 34, blur=int(self.W * 0.11))
        return img

    def _chrome(self, img: Image.Image, page: int, total: int) -> None:
        """统一页眉、页码与底部进度条"""
        d = ImageDraw.Draw(img)
        muted, accent = self.theme["muted"], self.theme["accent"]
        s = self.S
        lm, tm = self.M, int(62 * s)
        box = int(62 * s)
        d.rounded_rectangle([lm, tm, lm + box, tm + box], radius=int(16 * s),
                            fill=accent)
        f_logo = self.f(30, True)
        d.text((lm + box / 2, tm + box / 2), "AI", font=f_logo,
               fill=(12, 22, 40), anchor="mm")

        f_head = self.f(29)
        brand = tk.ellipsis(self.brand, f_head, self.W * 0.42)
        x = lm + box + int(20 * s)
        d.text((x, tm + box / 2), brand, font=f_head, fill=muted, anchor="lm")
        if self.subject:
            sub = tk.ellipsis("· " + self.subject, f_head,
                              self.W - self.M - (x + tk.text_w(brand, f_head) + 200 * s))
            d.text((x + tk.text_w(brand, f_head), tm + box / 2), sub,
                   font=f_head, fill=muted, anchor="lm")

        if total:
            f_page = self.f(32, True)
            label, total_label = f"{page:02d}", f" / {total:02d}"
            d.text((self.W - self.M - tk.text_w(total_label, f_page), tm + box / 2),
                   total_label, font=f_page, fill=muted, anchor="lm")
            d.text((self.W - self.M - tk.text_w(total_label, f_page)
                    - tk.text_w(label, f_page), tm + box / 2),
                   label, font=f_page, fill=accent, anchor="lm")

        bar_y = self.H - int(74 * s)
        d.rounded_rectangle([lm, bar_y, self.W - lm, bar_y + int(8 * s)],
                            radius=int(4 * s), fill=self._rgba(self.theme["text"], 26))
        if total:
            ratio = max(0.02, min(1.0, page / total))
            d.rounded_rectangle([lm, bar_y, lm + int((self.W - 2 * lm) * ratio),
                                 bar_y + int(8 * s)],
                                radius=int(4 * s), fill=accent)

    def _card(self, img: Image.Image, box, radius: int | None = None,
              alpha: int = 210, border: bool = True) -> None:
        layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        r = radius if radius is not None else int(28 * self.S)
        d.rounded_rectangle(box, radius=r,
                            fill=self._rgba(self.theme["card"], alpha),
                            outline=self._rgba(self.theme["accent"], 90) if border else None,
                            width=2)
        img.alpha_composite(layer)

    def _headline(self, img: Image.Image, title: str, y: int | None = None,
                  max_lines: int = 1, size: int = 60) -> int:
        """标题 + 左侧强调竖条，返回标题区底部 y"""
        d = ImageDraw.Draw(img)
        y = self.TOP - int(40 * self.S) if y is None else y
        lines, font = tk.fit_text(title, self.W - 2 * self.M - int(40 * self.S),
                                  max_lines,
                                  [int(size * self.S), int((size - 6) * self.S),
                                   int((size - 12) * self.S), int(38 * self.S)], True)
        bar_h = len(lines) * (font.size + 12)
        d.rounded_rectangle([self.M, y + 8, self.M + int(10 * self.S), y + bar_h],
                            radius=int(5 * self.S), fill=self.theme["accent"])
        cy = y
        for ln in lines:
            d.text((self.M + int(34 * self.S), cy), ln, font=font,
                   fill=self.theme["text"])
            cy += font.size + 12
        return cy

    def _bullet_rows(self, img: Image.Image, bullets: list[str], top: int,
                     bottom: int, x0: int, width: int, max_items: int = 5,
                     head_size: int = 34, desc_size: int = 26,
                     show_head: bool = True) -> None:
        """紧凑的「序号 + 小标题 + 说明」行，用于图文混排的文字栏。

        show_head=False 时只显示说明正文 —— 竖版里插图已把小标题放在正上方，
        再重复一遍会显得冗余。
        """
        d = ImageDraw.Draw(img)
        items = [str(b) for b in bullets if str(b).strip()][:max_items] or ["—"]
        n = len(items)
        gap = int(16 * self.S)
        row_h = (bottom - top - gap * (n - 1)) / n
        for i, it in enumerate(items):
            y0 = top + i * (row_h + gap)
            cy = y0 + row_h / 2
            has_desc = "|" in it
            head, _, desc = it.partition("|")

            # 序号圆点
            r = int(16 * self.S)
            cx = x0 + r
            d.ellipse([cx - r, cy - r, cx + r, cy + r],
                      fill=self._rgba(self.theme["accent"], 40),
                      outline=self.theme["accent"], width=2)
            f_num = self.f(20, True)
            d.text((cx, cy), str(i + 1), font=f_num, fill=self.theme["accent2"],
                   anchor="mm")

            tx = x0 + r * 2 + int(18 * self.S)
            tw = width - (tx - x0)
            if show_head or not desc.strip():
                f_h = self.f(head_size, True)
                if has_desc and desc.strip():
                    d.text((tx, cy - row_h * 0.17),
                           tk.ellipsis(head, f_h, tw), font=f_h,
                           fill=self.theme["text"], anchor="lm")
                    f_d = self.f(desc_size)
                    d.text((tx, cy + row_h * 0.21),
                           tk.ellipsis(desc, f_d, tw), font=f_d,
                           fill=self.theme["muted"], anchor="lm")
                else:
                    lines, font = tk.fit_text(
                        head, tw, max(1, int(row_h // (head_size * self.S + 8))),
                        [int(head_size * self.S), int((head_size - 4) * self.S),
                         int((head_size - 8) * self.S)], True)
                    ty = cy - (len(lines) - 1) * (font.size + 6) / 2
                    for ln in lines:
                        d.text((tx, ty), ln, font=font, fill=self.theme["text"],
                               anchor="lm")
                        ty += font.size + 6
            else:
                # 只显示说明正文（插图已给出小标题）
                f_d = self.f(desc_size + 3)
                avail = max(1, int(row_h // (f_d.size + 8)))
                lines, font = tk.fit_text(desc, tw, avail,
                                          [f_d.size, int(f_d.size * 0.88)])
                ty = cy - (len(lines) - 1) * (font.size + 8) / 2
                for ln in lines:
                    d.text((tx, ty), ln, font=font, fill=self.theme["muted"],
                           anchor="lm")
                    ty += font.size + 8

    # ------------------------------------------------------------------
    # 版式：封面 / 片尾 / 引语
    # ------------------------------------------------------------------
    def cover(self, title: str, subtitle: str = "", meta: str = "",
              out_path: str = "", total: int = 0, art: Image.Image | None = None) -> str:
        img = self._canvas()
        if art is not None:
            img = Image.alpha_composite(img, art)
        d = ImageDraw.Draw(img)
        s = self.S
        top = int(self.H * 0.28) if self.portrait else int(self.H * 0.30)

        tag = self.subject or "知识讲解"
        f_tag = self.f(32)
        tw = tk.text_w(tag, f_tag) + int(64 * s)
        d.rounded_rectangle([self.M, top, self.M + tw, top + int(68 * s)],
                            radius=int(34 * s), fill=self._rgba(self.theme["accent"], 46),
                            outline=self._rgba(self.theme["accent"], 160), width=2)
        d.text((self.M + int(32 * s), top + int(34 * s)), tk.ellipsis(tag, f_tag, self.W - 2 * self.M),
               font=f_tag, fill=self.theme["accent2"], anchor="lm")

        y = top + int(110 * s)
        lines, font = tk.fit_text(title, self.W - 2 * self.M, 4 if self.portrait else 3,
                                  [int(108 * s), int(96 * s), int(84 * s),
                                   int(72 * s), int(60 * s)], True)
        for ln in lines:
            d.text((self.M, y), ln, font=font, fill=self.theme["text"])
            y += int(font.size * 1.32)

        d.rounded_rectangle([self.M, y + int(8 * s), self.M + int(220 * s),
                             y + int(20 * s)],
                            radius=int(6 * s), fill=self.theme["accent"])

        if subtitle:
            y += int(62 * s)
            sub_lines, f_sub = tk.fit_text(subtitle, self.W - 2 * self.M - int(40 * s), 2,
                                           [int(40 * s), int(36 * s), int(32 * s)])
            for ln in sub_lines:
                d.text((self.M, y), ln, font=f_sub, fill=self.theme["muted"])
                y += f_sub.size + 10

        if meta:
            f_meta = self.f(32)
            my = self.H - int(250 * s)
            for part in str(meta).split("｜"):
                d.text((self.M, my), tk.ellipsis(part, f_meta, self.W - 2 * self.M),
                       font=f_meta, fill=self.theme["muted"])
                my += int(48 * s)

        self._chrome(img, 1, total)
        return self._save(img, out_path)

    def ending(self, title: str, points: list[str], page: int, total: int,
               out_path: str = "", art: Image.Image | None = None) -> str:
        img = self._canvas()
        if art is not None:
            img = Image.alpha_composite(img, art)
        d = ImageDraw.Draw(img)
        s = self.S

        y = int(self.H * 0.26)
        lines, font = tk.fit_text(title, self.W - 2 * self.M, 2,
                                  [int(96 * s), int(84 * s), int(72 * s), int(60 * s)], True)
        for ln in lines:
            d.text((self.M, y), ln, font=font, fill=self.theme["text"])
            y += int(font.size * 1.30)
        d.rounded_rectangle([self.M, y + int(20 * s), self.M + int(260 * s),
                             y + int(32 * s)], radius=int(6 * s),
                            fill=self.theme["accent"])
        y += int(90 * s)

        f_item = self.f(38)
        for p in [p for p in points if str(p).strip()][:4]:
            d.ellipse([self.M + int(4 * s), y + int(16 * s),
                       self.M + int(20 * s), y + int(32 * s)],
                      fill=self.theme["accent2"])
            d.text((self.M + int(44 * s), y),
                   tk.ellipsis(str(p).split("|")[0], f_item,
                               self.W - 2 * self.M - int(80 * s)),
                   font=f_item, fill=self.theme["muted"])
            y += int(74 * s)

        self._chrome(img, page, total)
        return self._save(img, out_path)

    def quote(self, title: str, bullets: list[str], page: int, total: int,
              out_path: str = "", art: Image.Image | None = None) -> str:
        img = self._canvas()
        overlay = art is not None and art.width >= self.W      # 满屏装饰层
        if overlay:
            img = Image.alpha_composite(img, art)
        d = ImageDraw.Draw(img)
        s = self.S

        # 有插图时文字让位：横版改「左文右图」，竖版把插图放到下方
        art_box = None
        text_right = self.W - self.M - int(120 * s)
        text_bottom = self.H - int(240 * s)
        if art is not None and not overlay:
            art_box = self._art_box("quote", self._head_bottom_est())
            if self.portrait:
                text_bottom = art_box[1] - int(30 * s)
            else:
                text_right = art_box[0] - int(40 * s)

        f_quote = self.f(150, True)
        d.text((self.M - int(10 * s), self.H * 0.20), "“", font=f_quote,
               fill=self._rgba(self.theme["accent"], 90))

        text = bullets[0] if bullets else title
        lines, font = tk.fit_text(text, text_right - self.M - int(60 * s),
                                  6 if self.portrait else 5,
                                  [int(76 * s), int(68 * s), int(60 * s), int(52 * s),
                                   int(44 * s), int(38 * s)], True)
        total_h = len(lines) * int(font.size * 1.42)
        y = int((int(self.H * 0.20) + text_bottom) / 2 - total_h / 2)
        for ln in lines:
            d.text((self.M + int(60 * s), y), ln, font=font, fill=self.theme["text"])
            y += int(font.size * 1.42)

        if title and title != text:
            f_sub = self.f(36)
            d.text((self.M + int(60 * s), y + int(30 * s)),
                   tk.ellipsis("— " + title, f_sub, text_right - self.M),
                   font=f_sub, fill=self.theme["muted"])

        d.rounded_rectangle([self.M + int(60 * s), self.H - int(260 * s),
                             self.M + int(300 * s), self.H - int(248 * s)],
                            radius=int(6 * s), fill=self.theme["accent"])
        if art_box:
            self._paste_art(img, art, art_box)
        self._chrome(img, page, total)
        return self._save(img, out_path)

    # ------------------------------------------------------------------
    # 版式：要点卡片
    # ------------------------------------------------------------------
    def points(self, title: str, bullets: list[str], page: int, total: int,
               out_path: str = "", max_items: int = 4,
               art: Image.Image | None = None) -> str:
        img = self._canvas()
        head_bottom = self._headline(img, title)
        d = ImageDraw.Draw(img)
        s = self.S

        items = [b for b in bullets if str(b).strip()][:max_items] or [title]
        # 有插图时卡片让位：横版收窄到左侧，竖版缩短到上方
        art_box = self._art_box("points", head_bottom) if art is not None else None
        right, bottom = self._text_area(art_box)
        top = head_bottom + int(40 * s)
        available = bottom - top
        gap = self.fmt["gap"]
        card_h = int((available - gap * (len(items) - 1)) / len(items))

        for i, item in enumerate(items):
            y0 = top + i * (card_h + gap)
            self._card(img, [self.M, y0, right, y0 + card_h])
            d = ImageDraw.Draw(img)

            r = min(int(42 * s), card_h // 2 - 8)
            cx, cy = self.M + int(40 * s) + r, y0 + card_h // 2
            d.ellipse([cx - r, cy - r, cx + r, cy + r],
                      fill=self._rgba(self.theme["accent"], 44),
                      outline=self.theme["accent"], width=2)
            f_num = self.f(r * 1.05 / s, True)
            d.text((cx, cy), str(i + 1), font=f_num,
                   fill=self.theme["accent2"], anchor="mm")
            term, _, desc = str(item).partition("|")
            text_x = cx + r + int(40 * s)
            tw = right - int(50 * s) - text_x
            if desc.strip():
                f_term = self.f(46, True)
                d.text((text_x, y0 + int(34 * s)), tk.ellipsis(term, f_term, tw),
                       font=f_term, fill=self.theme["text"])
                lines, f_desc = tk.fit_text(desc, tw, max(1, (card_h - int(110 * s)) // int(46 * s)),
                                            [int(36 * s), int(32 * s), int(28 * s)])
                yy = y0 + int(34 * s) + f_term.size + int(22 * s)
                for ln in lines:
                    d.text((text_x, yy), ln, font=f_desc, fill=self.theme["muted"])
                    yy += f_desc.size + 10
            else:
                lines, f_term = tk.fit_text(term, tw, max(1, (card_h - int(60 * s)) // int(60 * s)),
                                            [int(46 * s), int(40 * s), int(34 * s)], True)
                yy = y0 + card_h / 2 - (len(lines) * (f_term.size + 10)) / 2
                for ln in lines:
                    d.text((text_x, yy), ln, font=f_term, fill=self.theme["text"])
                    yy += f_term.size + 10

        if art_box:
            self._paste_art(img, art, art_box)
        self._chrome(img, page, total)
        return self._save(img, out_path)

    # ------------------------------------------------------------------
    # 版式：图文混排（插图 + 要点）
    # ------------------------------------------------------------------
    def board(self, title: str, bullets: list[str], page: int, total: int,
              out_path: str = "", art: Image.Image | None = None) -> str:
        img = self._canvas()
        head_bottom = self._headline(img, title)
        s = self.S
        items = [str(b) for b in bullets if str(b).strip()][:5] or [title]

        if self.portrait:
            # 上：插图；下：要点
            art_top = head_bottom + int(30 * s)
            art_h = int(self.H * 0.36)
            art_box = [self.M, art_top, self.W - self.M, art_top + art_h]
            text_top = art_top + art_h + int(34 * s)
            text_bottom = self.H - self.BOTTOM
            self._paste_art(img, art, art_box)
            self._bullet_rows(img, items, text_top, text_bottom,
                              self.M, self.W - 2 * self.M, show_head=False)
        else:
            # 左：要点；右：插图
            content_top = head_bottom + int(30 * s)
            content_bottom = self.H - self.BOTTOM
            inner = self.W - 2 * self.M
            left_w = int(inner * 0.52)
            self._bullet_rows(img, items, content_top, content_bottom,
                              self.M, left_w)
            art_box = [self.M + inner - int(inner * 0.42), content_top,
                       self.W - self.M, content_bottom]
            self._paste_art(img, art, art_box)

        self._chrome(img, page, total)
        return self._save(img, out_path)

    def _head_bottom_est(self) -> int:
        """估算标题区底部（_headline 单行 60 号字时的高度）。

        插图需要在排版之前就确定画布尺寸，此时还不知道标题实际占多高，
        所以用估算值；它与实际值的偏差由 _paste_art 的等比裁切吸收。
        """
        return self.TOP - int(40 * self.S) + int(60 * self.S) + 12

    def _art_box(self, layout: str, head_bottom: int) -> list[int]:
        """插图区域。

        横版：左文字 / 右插图；竖版：文字在上 / 插图整宽占下方。
        art_size() 与各版式共用这一套算式，保证「按目标尺寸画的插图」
        正好贴进去，不会被裁掉内容。
        """
        s, M = self.S, self.M
        inner = self.W - 2 * M
        top = head_bottom + int(30 * s)
        bottom = self.H - self.BOTTOM
        if self.portrait:
            h = int((bottom - top) * 0.40)
            return [M, bottom - h, self.W - M, bottom]
        w = int(inner * (0.42 if layout == "board" else 0.40))
        return [self.W - M - w, top, self.W - M, bottom]

    def art_size(self, layout: str, kind: str = "") -> tuple[int, int]:
        """该版式 + 图型下插图的目标像素尺寸。

        插图按这个尺寸精确生成，贴上去时就不需要缩放/裁剪，
        既避免流程链被裁掉，也省一次重采样。
        """
        # 装饰性主视觉：整屏叠加（封面 / 片尾，以及横版的流程页、对照页——
        # 后两者本身就是「卡片+箭头」的图形版式，再加右栅插图反而挤）
        if kind == "motif" or layout in ("cover", "ending"):
            return (self.W, self.H)
        if layout == "board" and self.portrait:
            return (self.W - 2 * self.M, int(self.H * 0.36))
        box = self._art_box(layout, self._head_bottom_est())
        return (box[2] - box[0], box[3] - box[1])

    def _text_area(self, art_box) -> tuple[int, int]:
        """文字区的右下边界：横版给右栅插图让位，竖版给下方插图让位"""
        s = self.S
        if art_box is None:
            return self.W - self.M, self.H - self.BOTTOM
        if self.portrait:
            return self.W - self.M, art_box[1] - int(26 * s)
        return art_box[0] - int(36 * s), self.H - self.BOTTOM

    def _paste_art(self, img: Image.Image, art: Image.Image | None, box) -> None:
        """把插图等比缩放到目标区域并粘贴（区域留白由插图自身底板填充）"""
        x0, y0, x1, y1 = [int(v) for v in box]
        w, h = max(1, x1 - x0), max(1, y1 - y0)
        if art is None:
            return
        # 按比例把插图缩放到填满区域（fcover），居中裁剪
        ar, br = art.width / art.height, w / h
        if ar > br:
            nh = h
            nw = int(h * ar)
        else:
            nw = w
            nh = int(w / ar)
        scaled = art.resize((nw, nh), Image.LANCZOS)
        left = max(0, (nw - w) // 2)
        top = max(0, (nh - h) // 2)
        img.alpha_composite(scaled.crop((left, top, left + w, top + h)), (x0, y0))

    # ------------------------------------------------------------------
    # 版式：流程 / 对比 / 回顾
    # ------------------------------------------------------------------
    def steps(self, title: str, bullets: list[str], page: int, total: int,
              out_path: str = "", art: Image.Image | None = None) -> str:
        img = self._canvas()
        # 横版：流程卡片本身就是「编号 + 箭头」的图形版式，插图作为整屏装饰层垫在下面
        overlay = art is not None and art.width >= self.W
        if overlay:
            img = Image.alpha_composite(img, art)
        head_bottom = self._headline(img, title)
        s = self.S

        if art is not None and not overlay and self.portrait:
            # 竖版：交给插图层的纵向流程链（版式更紧凑、可读性更好）
            box = [self.M, head_bottom + int(30 * s), self.W - self.M,
                   self.H - self.BOTTOM]
            self._paste_art(img, art, box)
            self._chrome(img, page, total)
            return self._save(img, out_path)

        d = ImageDraw.Draw(img)
        items = [str(b) for b in bullets if str(b).strip()][:5] or [title]
        n = len(items)
        top = head_bottom + int(70 * s)
        card_h = self.H - self.BOTTOM - top - int(40 * s)
        gap = int(30 * s)
        card_w = int((self.W - 2 * self.M - gap * (n - 1)) / n)

        for i, raw in enumerate(items):
            x0 = self.M + i * (card_w + gap)
            head, _, desc = str(raw).partition("|")
            self._card(img, [x0, top, x0 + card_w, top + card_h])
            d = ImageDraw.Draw(img)

            f_num = self.f(70, True)
            d.text((x0 + int(40 * s), top + int(34 * s)), f"{i + 1:02d}",
                   font=f_num, fill=self._rgba(self.theme["accent"], 190))

            inner_w = card_w - int(80 * s)
            lines, f_t = tk.fit_text(head, inner_w, 3,
                                     [int(44 * s), int(40 * s), int(36 * s), int(30 * s)], True)
            yy = top + int(140 * s)
            for ln in lines:
                d.text((x0 + int(40 * s), yy), ln, font=f_t, fill=self.theme["text"])
                yy += f_t.size + 12
            if desc.strip():
                lines, f_d = tk.fit_text(desc, inner_w, 4,
                                         [int(32 * s), int(28 * s), int(24 * s)])
                yy += int(14 * s)
                for ln in lines:
                    d.text((x0 + int(40 * s), yy), ln, font=f_d,
                           fill=self.theme["muted"])
                    yy += f_d.size + 10

            if i < n - 1:
                acx, acy = x0 + card_w + gap / 2, top + card_h / 2
                d.polygon([(acx - int(12 * s), acy - int(14 * s)),
                           (acx + int(12 * s), acy),
                           (acx - int(12 * s), acy + int(14 * s))],
                          fill=self.theme["accent"])

        self._chrome(img, page, total)
        return self._save(img, out_path)

    def compare(self, title: str, bullets: list[str], page: int, total: int,
                out_path: str = "", art: Image.Image | None = None) -> str:
        img = self._canvas()
        # 横版：左右对照卡片已经是图形版式，插图作为整屏装饰层垫在下面
        overlay = art is not None and art.width >= self.W
        if overlay:
            img = Image.alpha_composite(img, art)
        head_bottom = self._headline(img, title)
        s = self.S

        if art is not None and not overlay and self.portrait:
            # 竖版：交给插图层的上下对照板
            box = [self.M, head_bottom + int(30 * s), self.W - self.M,
                   self.H - self.BOTTOM]
            self._paste_art(img, art, box)
            self._chrome(img, page, total)
            return self._save(img, out_path)

        d = ImageDraw.Draw(img)
        raw = [str(b) for b in bullets if str(b).strip()][:4]
        half = max(1, len(raw) // 2)
        left = [str(b).split("|")[0] for b in raw[:half]] or ["常见误区"]
        right = [(str(b).split("|")[1] if "|" in str(b) else str(b))
                 for b in raw[half:]] or ["正确认识"]

        top = head_bottom + int(40 * s)
        card_h = self.H - self.BOTTOM - top
        gap = int(44 * s)
        card_w = int((self.W - 2 * self.M - gap) / 2)

        for col, (heading, items, color) in enumerate((
                ("常见误区", left, (255, 138, 118)),
                ("正确认识", right, self.theme["accent2"]))):
            x0 = self.M + col * (card_w + gap)
            self._card(img, [x0, top, x0 + card_w, top + card_h])
            d = ImageDraw.Draw(img)
            d.rounded_rectangle([x0 + int(40 * s), top + int(36 * s),
                                 x0 + int(260 * s), top + int(96 * s)],
                                radius=int(30 * s), fill=self._rgba(color, 46),
                                outline=color, width=2)
            f_h = self.f(34, True)
            d.text((x0 + int(62 * s), top + int(66 * s)), heading, font=f_h,
                   fill=color, anchor="lm")

            yy = top + int(150 * s)
            inner_w = card_w - int(110 * s)
            for it in items[:5]:
                d.ellipse([x0 + int(44 * s), yy + int(16 * s),
                           x0 + int(60 * s), yy + int(32 * s)], fill=color)
                lines, f_b = tk.fit_text(it, inner_w, 2,
                                         [int(40 * s), int(36 * s), int(32 * s), int(28 * s)])
                for ln in lines:
                    d.text((x0 + int(82 * s), yy), ln, font=f_b, fill=self.theme["text"])
                    yy += f_b.size + 10
                yy += int(26 * s)

        self._chrome(img, page, total)
        return self._save(img, out_path)

    def summary(self, title: str, bullets: list[str], page: int, total: int,
                out_path: str = "", art: Image.Image | None = None) -> str:
        img = self._canvas()
        head_bottom = self._headline(img, title)
        d = ImageDraw.Draw(img)
        s = self.S

        items = [str(b).split("|")[0] for b in bullets if str(b).strip()][:6]
        art_box = self._art_box("summary", head_bottom) if art is not None else None
        right, bottom = self._text_area(art_box)
        top = head_bottom + int(50 * s)
        row_h = min(int(108 * s), int((bottom - top) / max(1, len(items))))
        f_num = self.f(40, True)
        for i, it in enumerate(items):
            y = top + i * row_h
            d.rounded_rectangle([self.M, y, self.M + int(76 * s), y + int(68 * s)],
                                radius=int(20 * s),
                                fill=self._rgba(self.theme["accent"], 44))
            d.text((self.M + int(38 * s), y + int(34 * s)), str(i + 1), font=f_num,
                   fill=self.theme["accent2"], anchor="mm")
            f_item = self.f(42)
            d.text((self.M + int(108 * s), y + int(34 * s)),
                   tk.ellipsis(it, f_item, right - self.M - int(140 * s)),
                   font=f_item, fill=self.theme["text"], anchor="lm")

        if art_box:
            self._paste_art(img, art, art_box)
        self._chrome(img, page, total)
        return self._save(img, out_path)

    # ------------------------------------------------------------------
    # 输出与分派
    # ------------------------------------------------------------------
    @staticmethod
    def _save(img: Image.Image, out_path: str) -> str:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        img.convert("RGB").save(out_path, "PNG", optimize=True)
        return out_path

    def render_shot(self, shot: dict, page: int, total: int, out_path: str,
                    art: Image.Image | None = None) -> str:
        layout = (shot.get("layout") or "points").lower()
        title = shot.get("title") or shot.get("scene") or ""
        bullets = shot.get("bullets") or []
        if layout == "cover":
            return self.cover(title, shot.get("subtitle", ""),
                              shot.get("meta", ""), out_path, total, art)
        if layout == "ending":
            return self.ending(title, bullets, page, total, out_path, art)
        if layout == "quote":
            return self.quote(title, bullets, page, total, out_path, art)
        if layout == "steps":
            return self.steps(title, bullets, page, total, out_path, art)
        if layout == "compare":
            return self.compare(title, bullets, page, total, out_path, art)
        if layout == "summary":
            return self.summary(title, bullets, page, total, out_path, art)
        if layout == "board" and art is not None:
            return self.board(title, bullets, page, total, out_path, art)
        return self.points(title, bullets, page, total, out_path, art=art)
