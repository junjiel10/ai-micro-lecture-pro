# -*- coding: utf-8 -*-
"""插图绘制层：把分镜内容变成结构化图形（不需要任何在线服务）

为什么用「程序化插图」而不是文生图？
  · 微课里的插图主要是 关系 / 流程 / 分类 / 对照 这类**结构性图形**，
    用矢量方式画出来比 AI 生图更准确（AI 生图经常把文字画错，也容易编造内容）；
  · 不联网、不花钱、不挑显卡，任何电脑上都能稳定产出；
  · 如果确实需要写实配图，可另配 IMAGE_API_KEY 走外部文生图接口（见 llm_client）。

支持 8 种插图：
  motif         抽象主视觉（封面 / 片尾 / 原生图形版式的背景装饰）
  concept_map   概念结构图（中心概念 → 若干要素，树状连线）
  flow_chain    流程链（编号步骤 + 向下箭头）
  tag_cloud     标签云（关键词矩阵）
  split_compare 左右对照板（误区 / 正确认识）
  index_rail    要点索引轨道（几条并列要点串在一条主轴上）
  radial_index  总览环图（中心 + 环形编号节点，用于回顾页）
  spotlight     聚焦主视觉（一个大圆徽 + 关键词气泡，用于引语 / 概念页）

版式与图型的对应关系见 slides.SlideRenderer.art_size：目标是**每一屏都有图**，
而不是只有「图文混排」那一种版式才有。
"""
from __future__ import annotations

import math

from PIL import Image, ImageDraw, ImageFilter

from . import textkit as tk


class Artist:
    """按主题配色与画布尺寸绘制插图"""

    def __init__(self, theme: dict, size: tuple[int, int], scale: float = 1.0):
        self.t = theme
        self.w, self.h = int(size[0]), int(size[1])
        self.S = float(scale)
        self.accent = theme["accent"]
        self.accent2 = theme["accent2"]
        self.text = theme["text"]
        self.muted = theme["muted"]
        self.card = theme["card"]

    # ------------------------------------------------------------------
    # 基础工具
    # ------------------------------------------------------------------
    def f(self, size: float, bold: bool = False):
        return tk.get_font(size * self.S, bold)

    def _new(self, alpha: int = 0) -> Image.Image:
        return Image.new("RGBA", (self.w, self.h), (0, 0, 0, alpha))

    def _rgba(self, c, a):
        return (c[0], c[1], c[2], int(a))

    def plate(self, inset: int = 0, radius: int | None = None,
              alpha: int = 205) -> Image.Image:
        """半透明玻璃底板（插图与幻灯片背景之间做层次）"""
        img = self._new()
        d = ImageDraw.Draw(img)
        r = radius if radius is not None else int(28 * self.S)
        box = [inset, inset, self.w - 1 - inset, self.h - 1 - inset]
        d.rounded_rectangle(box, radius=r, fill=self._rgba(self.card, alpha),
                            outline=self._rgba(self.accent, 80), width=2)
        return img

    def _pill(self, d, box, radius, fill, outline=None, width=2):
        d.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)

    def _badge(self, d, cx, cy, r, label, fill, fg):
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill)
        f = self.f(r * 1.05 / self.S, True)      # r 是像素值，换回设计字号
        d.text((cx, cy), str(label), font=f, fill=fg, anchor="mm")

    def _arrow_down(self, d, cx, y0, y1, color):
        d.line([cx, y0, cx, y1 - 10 * self.S], fill=color, width=max(2, int(3 * self.S)))
        s = 9 * self.S
        d.polygon([(cx - s, y1 - 12 * self.S), (cx + s, y1 - 12 * self.S), (cx, y1)],
                  fill=color)

    # ------------------------------------------------------------------
    # 1. 抽象主视觉
    # ------------------------------------------------------------------
    def motif(self, seed: int = 0, keywords: tuple = ()) -> Image.Image:
        """覆盖在封面/引语页上的抽象几何装饰（透明底）"""
        img = self._new()
        d = ImageDraw.Draw(img)
        w, h = self.w, self.h
        rnd = (seed % 7) / 7.0

        # 同心圆弧
        cx, cy = w * (0.62 + 0.1 * rnd), h * (0.42 + 0.08 * rnd)
        for i, rr in enumerate((0.42, 0.30, 0.19)):
            r = min(w, h) * rr
            box = [cx - r, cy - r, cx + r, cy + r]
            a = 70 - i * 18
            d.arc(box, start=-58 + i * 6, end=126 - i * 6,
                  fill=self._rgba(self.accent if i % 2 == 0 else self.accent2, a),
                  width=max(2, int((4 - i) * self.S)))

        # 圆点阵列
        step = max(18, int(26 * self.S))
        dot = max(2, int(3 * self.S))
        for gy in range(0, h, step):
            for gx in range(0, w, step):
                if ((gx // step) + (gy // step)) % 3 == 0:
                    a = 26 if (gx + gy) % 4 else 44
                    d.ellipse([gx, gy, gx + dot, gy + dot],
                              fill=self._rgba(self.text, a))

        # 斜向色带
        band = int(10 * self.S)
        for i in range(3):
            x0 = int(w * (0.06 + 0.05 * i))
            d.line([x0, h * 0.92, x0 + int(w * 0.22), h * 0.62],
                   fill=self._rgba(self.accent2 if i % 2 else self.accent, 60 - i * 15),
                   width=band)
        return img.filter(ImageFilter.GaussianBlur(0.6))

    # ------------------------------------------------------------------
    # 2. 概念结构图
    # ------------------------------------------------------------------
    def concept_map(self, center: str, items: list[str]) -> Image.Image:
        img = self.plate()
        d = ImageDraw.Draw(img)
        w, h = self.w, self.h
        pad = int(22 * self.S)

        items = [str(x).split("|")[0] for x in items if str(x).strip()][:4] or [str(center)]
        n = len(items)

        # 中心概念
        f_c = self.f(34, True)
        label = tk.ellipsis(str(center), f_c, w - pad * 4)
        cw = max(int(tk.text_w(label, f_c) + pad * 2.6), int(w * 0.5))
        ch = int(72 * self.S)
        ccx, ccy = w // 2, int(h * 0.145)
        self._pill(d, [ccx - cw // 2, ccy - ch // 2, ccx + cw // 2, ccy + ch // 2],
                   ch // 2, self._rgba(self.accent, 62), self._rgba(self.accent, 200), 2)
        d.text((ccx, ccy), label, font=f_c, fill=self.text, anchor="mm")

        # 分支网格
        cols = 2 if n > 1 else 1
        rows = math.ceil(n / cols)
        grid_top = int(h * 0.36)
        grid_bottom = h - pad
        cell_w = (w - pad * (cols + 1)) / cols
        cell_h = (grid_bottom - grid_top - pad * (rows - 1)) / rows
        trunk_y = int((ccy + ch // 2 + grid_top) / 2)
        accent = self._rgba(self.accent, 170)

        # 主干
        d.line([ccx, ccy + ch // 2, ccx, trunk_y], fill=accent,
               width=max(2, int(3 * self.S)))

        f_item = self.f(26)
        for i, it in enumerate(items):
            r, c = divmod(i, cols)
            if n == 3 and i == 2:                    # 3 个时最后一个居中
                x0 = (w - cell_w) / 2
            else:
                x0 = pad + c * (cell_w + pad)
            y0 = grid_top + r * (cell_h + pad)
            x1, y1 = x0 + cell_w, y0 + cell_h
            bx = int((x0 + x1) / 2)

            # 连线：主干 → 横向支路 → 盒顶
            if abs(bx - ccx) > 4:
                d.line([ccx, trunk_y, bx, trunk_y], fill=accent,
                       width=max(2, int(2.4 * self.S)))
            d.line([bx, trunk_y, bx, y0], fill=accent, width=max(2, int(2.4 * self.S)))

            self._pill(d, [x0, y0, x1, y1], int(18 * self.S),
                       self._rgba(self.accent, 34), self._rgba(self.accent, 110), 2)
            lines, font = tk.fit_text(it, cell_w - pad * 1.6,
                                      max(1, int(cell_h // (26 * self.S + 8))),
                                      [int(30 * self.S), int(27 * self.S), int(24 * self.S)], True)
            total = len(lines) * (font.size + 6)
            ty = y0 + (cell_h - total) / 2
            for ln in lines:
                d.text((bx, ty + font.size / 2), ln, font=font, fill=self.text, anchor="mm")
                ty += font.size + 6
        return img

    # ------------------------------------------------------------------
    # 3. 流程链
    # ------------------------------------------------------------------
    def flow_chain(self, items: list[str], with_desc: bool = True) -> Image.Image:
        """纵向流程链。与文字栏混排时传 with_desc=False，只画步骤名，避免重复。"""
        img = self.plate()
        d = ImageDraw.Draw(img)
        w, h = self.w, self.h
        pad = int(22 * self.S)
        items = [str(x) for x in items if str(x).strip()][:5] or ["步骤"]
        n = len(items)

        row_h = (h - pad * 2 - int(26 * self.S) * (n - 1)) / n
        r = min(int(row_h * 0.30), int(34 * self.S))
        x_badge = pad + r + int(6 * self.S)
        x_text = x_badge + r + int(20 * self.S)
        box_w = w - pad - x_text

        f_head = self.f(27, True)
        f_desc = self.f(21)
        for i, it in enumerate(items):
            y0 = pad + i * (row_h + int(26 * self.S))
            cy = y0 + row_h / 2
            head, _, desc = str(it).partition("|")
            head, desc = head.strip(), (desc.strip() if with_desc else "")

            self._badge(d, x_badge, cy, r,
                        i + 1, self._rgba(self.accent, 56), self.accent2)
            self._pill(d, [x_text, y0, x_text + box_w, y0 + row_h],
                       int(14 * self.S), self._rgba(self.accent, 26),
                       self._rgba(self.accent, 90), 2)

            if desc:
                d.text((x_text + int(16 * self.S), cy - row_h * 0.20), head,
                       font=f_head, fill=self.text, anchor="lm")
                line = tk.ellipsis(desc, f_desc, box_w - int(30 * self.S))
                d.text((x_text + int(16 * self.S), cy + row_h * 0.20), line,
                       font=f_desc, fill=self.muted, anchor="lm")
            else:
                f_only = self.f(30, True) if not with_desc else self.f(28, True)
                lines, font = tk.fit_text(head, box_w - int(32 * self.S), 2,
                                          [f_only.size, int(f_only.size * 0.85)], True)
                ty = cy - (len(lines) - 1) * (font.size + 4) / 2
                for ln in lines:
                    d.text((x_text + int(16 * self.S), ty), ln,
                           font=font, fill=self.text, anchor="lm")
                    ty += font.size + 4

            if i < n - 1:
                self._arrow_down(d, x_badge, y0 + row_h, y0 + row_h + int(26 * self.S),
                                 self._rgba(self.accent, 160))
        return img

    # ------------------------------------------------------------------
    # 4. 标签云
    # ------------------------------------------------------------------
    def tag_cloud(self, tags: list[str]) -> Image.Image:
        img = self.plate()
        d = ImageDraw.Draw(img)
        w, h = self.w, self.h
        pad = int(22 * self.S)
        tags = [str(x).split("|")[0].strip() for x in tags if str(x).strip()][:8]
        if not tags:
            tags = ["要点"]

        sizes = [30, 25, 22, 27, 23, 21, 26, 22]
        x, y = pad, pad + int(8 * self.S)
        row_h = 0
        for i, tag in enumerate(tags):
            size = int(sizes[i % len(sizes)] * self.S)
            font = tk.get_font(size, i % 3 == 0)
            label = tk.ellipsis(tag, font, w - pad * 2)
            tw = int(tk.text_w(label, font)) + int(34 * self.S)
            th = size + int(20 * self.S)
            if x + tw > w - pad:                    # 换行
                x = pad
                y += row_h + int(12 * self.S)
                row_h = 0
            if y + th > h - pad:                    # 放不下就停
                break
            col = self.accent if i % 2 == 0 else self.accent2
            self._pill(d, [x, y, x + tw, y + th], th // 2,
                       self._rgba(col, 40 if i % 2 == 0 else 30),
                       self._rgba(col, 150), 2)
            d.text((x + tw / 2, y + th / 2), label, font=font,
                   fill=self.text if i % 2 == 0 else self.accent2, anchor="mm")
            x += tw + int(12 * self.S)
            row_h = max(row_h, th)
        return img

    # ------------------------------------------------------------------
    # 5. 左右对照板
    # ------------------------------------------------------------------
    def split_compare(self, left: list[str], right: list[str],
                      left_title: str = "常见误区", right_title: str = "正确认识"
                      ) -> Image.Image:
        img = self.plate()
        d = ImageDraw.Draw(img)
        w, h = self.w, self.h
        pad = int(22 * self.S)
        gap = int(18 * self.S)
        block_h = (h - pad * 2 - gap) / 2

        warm = (255, 150, 122)
        for idx, (title, items, col, mark) in enumerate((
                (left_title, left, warm, "✕"),
                (right_title, right, self.accent2, "✓"))):
            y0 = pad + idx * (block_h + gap)
            y1 = y0 + block_h
            self._pill(d, [pad, y0, w - pad, y1], int(18 * self.S),
                       self._rgba(col, 26), self._rgba(col, 120), 2)

            f_t = self.f(27, True)
            d.text((pad + int(18 * self.S), y0 + int(26 * self.S)), mark,
                   font=f_t, fill=col, anchor="lm")
            d.text((pad + int(52 * self.S), y0 + int(26 * self.S)), title,
                   font=f_t, fill=col, anchor="lm")

            items = [str(x).strip() for x in items if str(x).strip()][:3]
            if items:
                row_h = (block_h - int(56 * self.S)) / len(items)
                f_i = self.f(23)
                for j, it in enumerate(items):
                    ty = y0 + int(46 * self.S) + row_h * (j + 0.5)
                    d.ellipse([pad + int(22 * self.S), ty - 4 * self.S,
                               pad + int(22 * self.S) + 8 * self.S, ty + 4 * self.S],
                              fill=col)
                    line = tk.ellipsis(it, f_i, w - pad * 2 - int(60 * self.S))
                    d.text((pad + int(44 * self.S), ty), line, font=f_i,
                           fill=self.text, anchor="lm")
        return img

    # ------------------------------------------------------------------
    # 6. 要点索引轨道（并列要点页：为什么重要 / 应用场景…）
    # ------------------------------------------------------------------
    def index_rail(self, items: list[str], center: str = "") -> Image.Image:
        """一条主轴串起若干编号节点。

        与 concept_map 的区别：concept_map 画的是「中心→分支」的**层级**关系；
        这里几条要点是**并列**关系，所以用一条轴串起来，视觉语言不同，
        同一支视频里连着出现也不会显得重复。
        """
        img = self.plate()
        d = ImageDraw.Draw(img)
        w, h = self.w, self.h
        pad = int(24 * self.S)
        rows = [str(x).split("|")[0] for x in items if str(x).strip()][:5] or ["要点"]
        n = len(rows)

        head = int(46 * self.S) if str(center).strip() else 0
        rail_x = pad + int(44 * self.S)
        top = pad + head + int(30 * self.S)
        bottom = h - pad - int(20 * self.S)
        step = (bottom - top) / max(1, n)

        if head:
            f_c = self.f(24, True)
            d.text((pad, pad + int(8 * self.S)),
                   tk.ellipsis(str(center), f_c, w - pad * 2), font=f_c,
                   fill=self.muted, anchor="lm")

        # 主轴（上下贯穿）
        d.line([rail_x, top - int(18 * self.S), rail_x, bottom + int(6 * self.S)],
               fill=self._rgba(self.accent, 110), width=max(2, int(3 * self.S)))

        f_n = self.f(r_min := 27, True)
        f_t = self.f(27, True)
        for i, label in enumerate(rows):
            cy = top + step * (i + 0.5)
            r = int(26 * self.S)
            d.ellipse([rail_x - r, cy - r, rail_x + r, cy + r],
                      fill=self._rgba(self.accent, 60),
                      outline=self._rgba(self.accent, 210), width=2)
            d.text((rail_x, cy), str(i + 1), font=f_n, fill=self.accent2, anchor="mm")
            x0 = rail_x + r + int(18 * self.S)
            fw = w - pad - x0
            self._pill(d, [x0, cy - int(25 * self.S), x0 + fw, cy + int(25 * self.S)],
                       int(25 * self.S), self._rgba(self.accent, 26),
                       self._rgba(self.accent, 85), 2)
            d.text((x0 + int(16 * self.S), cy),
                   tk.ellipsis(label, f_t, fw - int(30 * self.S)),
                   font=f_t, fill=self.text, anchor="lm")
        return img

    # ------------------------------------------------------------------
    # 7. 总览环图（回顾页）
    # ------------------------------------------------------------------
    def radial_index(self, items: list[str], center: str = "") -> Image.Image:
        """中心 + 环形编号节点。

        回顾页左栅已经把要点逐条写全了，右侧再照抄一遍文字会显得像出错；
        所以这里只画「一共几条、共同构成一个整体」的结构，文案交给左栅。
        """
        img = self.plate()
        d = ImageDraw.Draw(img)
        w, h = self.w, self.h
        n = max(1, min(6, len(items) or 1))
        cx, cy = w / 2, h / 2
        R = int(min(w, h) * 0.30)

        # 外环：分成 n 段弧，暗示节点之间的先后/并列关系
        for i in range(n):
            a0 = math.degrees(-math.pi / 2 + 2 * math.pi * i / n) + 7
            a1 = math.degrees(-math.pi / 2 + 2 * math.pi * (i + 1) / n) - 7
            d.arc([cx - R, cy - R, cx + R, cy + R], start=a0, end=a1,
                  fill=self._rgba(self.accent, 150), width=max(2, int(3 * self.S)))

        # 中心圆
        r0 = int(min(w, h) * 0.165)
        d.ellipse([cx - r0, cy - r0, cx + r0, cy + r0],
                  fill=self._rgba(self.accent, 58),
                  outline=self._rgba(self.accent, 220), width=max(2, int(3 * self.S)))
        f_c = self.f(26, True)
        lines, font = tk.fit_text(str(center) or "总览", r0 * 1.6, 2,
                                  [int(28 * self.S), int(24 * self.S), int(20 * self.S)], True)
        ty = cy - (len(lines) * (font.size + 4)) / 2
        for ln in lines:
            d.text((cx, ty + font.size / 2), ln, font=font, fill=self.text, anchor="mm")
            ty += font.size + 4

        # 环形编号节点
        f_n = self.f(29, True)
        rr = int(29 * self.S)
        for i in range(n):
            ang = -math.pi / 2 + 2 * math.pi * i / n
            px, py = cx + R * math.cos(ang), cy + R * math.sin(ang)
            d.line([cx + r0 * math.cos(ang), cy + r0 * math.sin(ang), px, py],
                   fill=self._rgba(self.accent2, 140), width=max(2, int(2.5 * self.S)))
            d.ellipse([px - rr, py - rr, px + rr, py + rr],
                      fill=self._rgba(self.accent2, 58),
                      outline=self._rgba(self.accent2, 200), width=2)
            d.text((px, py), str(i + 1), font=f_n, fill=self.text, anchor="mm")
        return img

    # ------------------------------------------------------------------
    # 8. 聚焦主视觉（引语 / 概念界定页）
    # ------------------------------------------------------------------
    #: 按场景名选一个中心符号，让不同场景的圆徽有区别
    _GLYPH = (("问题", "?"), ("引入", "?"), ("概念", "◎"), ("定义", "◎"),
              ("案例", "★"), ("应用", "▶"), ("误区", "!"), ("建议", "✓"),
              ("回顾", "◆"), ("要素", "◈"))

    def spotlight(self, label: str, glyph: str = "") -> Image.Image:
        """带刻度的大圆徽 + 中心符号 + 下方标签。

        为什么只放符号不放文字：引语页左栅已经是整段原文，
        右侧再放文字气泡（哪怕是关键词）都会变成「同一段话写两遍」。
        """
        img = self.plate()
        d = ImageDraw.Draw(img)
        w, h = self.w, self.h
        pad = int(24 * self.S)
        if not glyph:
            glyph = next((g for k, g in self._GLYPH if k in str(label)), "✱")

        cx, cy = w / 2, h * 0.40
        r = int(min(w, h * 0.60) * 0.33)

        # 外圈刻度：让它看起来像「聚焦」而不是随便一个圆
        for i in range(28):
            ang = 2 * math.pi * i / 28
            long = i % 7 == 0
            r0 = r + int(12 * self.S)
            r1 = r0 + (int(14 * self.S) if long else int(7 * self.S))
            d.line([cx + r0 * math.cos(ang), cy + r0 * math.sin(ang),
                    cx + r1 * math.cos(ang), cy + r1 * math.sin(ang)],
                   fill=self._rgba(self.accent, 130 if long else 70),
                   width=max(2, int(3 * self.S if long else 2 * self.S)))

        # 双层圆徽
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=self._rgba(self.accent, 58))
        d.ellipse([cx - r, cy - r, cx + r, cy + r],
                  outline=self._rgba(self.accent, 220), width=max(2, int(4 * self.S)))
        r2 = int(r * 0.80)
        d.ellipse([cx - r2, cy - r2, cx + r2, cy + r2],
                  outline=self._rgba(self.accent2, 150), width=2)

        # 中心符号
        f_g = self.f(r * 1.05 / self.S, True)
        d.text((cx, cy), glyph, font=f_g, fill=self.text, anchor="mm")

        # 下方标签：用胶囊标出这一屏在讲什么
        f_l = self.f(27, True)
        label = str(label) or "要点"
        lw = min(w - pad * 2, tk.text_w(label, f_l) + int(60 * self.S))
        ly = int(h * 0.80)
        self._pill(d, [(w - lw) / 2, ly, (w + lw) / 2, ly + int(56 * self.S)],
                   int(28 * self.S), self._rgba(self.accent2, 30),
                   self._rgba(self.accent2, 140), 2)
        d.text((w / 2, ly + int(28 * self.S)), tk.ellipsis(label, f_l, lw - int(30 * self.S)),
               font=f_l, fill=self.text, anchor="mm")
        return img
