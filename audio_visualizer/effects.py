"""基于 Pillow 的透明背景特效渲染。每帧输出 RGBA 图像，背景 alpha=0。"""
from __future__ import annotations

import colorsys
import math
import random
from functools import lru_cache
from typing import Callable

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from .analysis import FrameFeatures

MODES: dict[str, str] = {
    "bottom": "🌈 底部频谱条",
    "mirror": "✨ 中央镜像扩散",
    "circle": "🔥 环形频谱",
    "dual_ring": "💫 双环旋转",
    "spiral": "🌀 螺旋星轨",
    "waveform": "〰️ 波形脉冲",
    "tunnel": "🕳️ 能量隧道",
    "particles": "🎆 粒子爆破",
}

THEMES: dict[str, str] = {
    "neon": "霓虹青紫（默认）",
    "rainbow": "全彩循环",
    "fire": "烈焰金红",
    "aurora": "极光青绿",
    "ice": "冰蓝纯白",
    "mono": "纯白",
    "purple_blue": "紫蓝渐变（左紫右蓝）",
}

# 纯中文名称（界面下拉使用，不含表情符号）
MODE_NAMES: dict[str, str] = {k: v.split(" ", 1)[-1] for k, v in MODES.items()}

# 界面中只提供固定可选值，不开放自定义输入
BAR_OPTIONS: tuple[int, ...] = (32, 64, 96, 128, 192)
GLOW_OPTIONS: tuple[float, ...] = (0.0, 0.5, 1.0, 1.5, 2.0)


def _clamp01(v: float) -> float:
    return 0.0 if v < 0 else 1.0 if v > 1 else v


class Renderer:
    """把音频特征渲染成透明 RGBA 帧。"""

    def __init__(
        self,
        width: int = 1920,
        height: int = 1080,
        mode: str = "circle",
        theme: str = "neon",
        glow: float = 1.0,
    ) -> None:
        if mode not in MODES:
            raise ValueError(f"未知效果: {mode}，可选: {', '.join(MODES)}")
        if theme not in THEMES:
            raise ValueError(f"未知配色: {theme}，可选: {', '.join(THEMES)}")
        self.w = int(width)
        self.h = int(height)
        self.mode = mode
        self.theme = theme
        self.glow = max(0.0, float(glow))
        self.s = float(min(self.w, self.h))
        self.rng = random.Random(20261122)
        self.particles: list[dict] = []
        self._draw_fn: Callable[[ImageDraw.ImageDraw, FrameFeatures], None] = getattr(
            self, f"_draw_{mode}"
        )

    def color(
        self, p: float, v: float, alpha: float | None = None,
        x: float | None = None,
    ) -> tuple[int, int, int, int]:
        """p=频谱位置 0..1, v=强度 0..1, x=水平位置 0..1（紫蓝渐变用）。返回 RGBA。"""
        p = _clamp01(p)
        v = _clamp01(v)
        tsec = getattr(self, "_time", 0.0)
        if self.theme == "neon":
            h, light = 0.50 + 0.22 * p, 0.48 + 0.42 * v
            sat = 1.0
        elif self.theme == "rainbow":
            h, light, sat = (p + tsec * 0.055) % 1.0, 0.48 + 0.40 * v, 1.0
        elif self.theme == "fire":
            h, light, sat = 0.02 + 0.11 * p + 0.02 * v, 0.42 + 0.45 * v, 1.0
        elif self.theme == "aurora":
            h, light, sat = 0.34 + 0.22 * p, 0.46 + 0.42 * v, 0.95
        elif self.theme == "ice":
            h, light, sat = 0.53 + 0.08 * p, 0.55 + 0.40 * v, 0.75
        elif self.theme == "purple_blue":
            # 左侧紫色(h≈0.80) → 右侧蓝色(h≈0.58)，按画面水平坐标渐变
            gx = _clamp01(x) if x is not None else p
            h, light, sat = 0.80 - 0.22 * gx, 0.42 + 0.44 * v, 0.92
        else:  # mono
            h, light, sat = 0.0, 0.55 + 0.45 * v, 0.0
        r, g, b = colorsys.hls_to_rgb(h % 1.0, min(0.98, light), sat)
        if alpha is None:
            alpha = 90 + 165 * v
        return (int(r * 255), int(g * 255), int(b * 255), int(max(0, min(255, alpha))))

    def render(self, features: FrameFeatures) -> Image.Image:
        self._time = features.time
        layer = Image.new("RGBA", (self.w, self.h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        # 局部辉光层：隧道/粒子在绘制时把发光环与光晕画到这里
        self._halo = Image.new("RGBA", (self.w, self.h), (0, 0, 0, 0))
        self._halo_draw = ImageDraw.Draw(self._halo)
        # 能量核层：渐变核心区域，最后叠加在主画面之上
        self._core = Image.new("RGBA", (self.w, self.h), (0, 0, 0, 0))
        # 柔光线条层：所有短线、圆环的柔光光带单独成层，
        # 半分辨率小半径模糊后垫在主线之下，形成平滑的中心-边缘渐变
        self._spokes = Image.new("RGBA", (self.w, self.h), (0, 0, 0, 0))
        self._spokes_draw = ImageDraw.Draw(self._spokes)
        # 渐变竖线层：底部/镜像/波形的频谱条由独立渐变竖线构成，避免相邻条粘成一片
        self._bars = Image.new("RGBA", (self.w, self.h), (0, 0, 0, 0))
        # 渐变圆环层：环形/双环/隧道的圆环由多层低透明度同心细环构成，边缘径向渐变
        self._rings = Image.new("RGBA", (self.w, self.h), (0, 0, 0, 0))
        self._rings_draw = ImageDraw.Draw(self._rings)
        self._draw_fn(draw, features)

        # 渐变圆环先合成到主体（圆环自身的渐变保留，不被柔光层再次糊掉）
        if self._rings.getbbox() is not None:
            layer = Image.alpha_composite(layer, self._rings)

        # 渐变竖线先合成到主体（不参与后续全画面模糊，保留条间空隙）
        if self._bars.getbbox() is not None:
            layer = Image.alpha_composite(layer, self._bars)

        # 渐变能量核叠加在主体之上（它本身就是柔化边缘的光球）
        if self._core.getbbox() is not None:
            layer = Image.alpha_composite(layer, self._core)

        # 柔光线带：在主线之下叠加柔化光晕层，让线条/圆环中心到边缘呈平滑渐变
        if self._spokes.getbbox() is not None and self.glow > 0:
            # 在 1/2 分辨率上做中等半径模糊：形成光带而非糊成一片
            hw, hh = max(2, self.w // 2), max(2, self.h // 2)
            soft = self._spokes.resize((hw, hh), Image.Resampling.BILINEAR)
            soft = soft.filter(ImageFilter.GaussianBlur(radius=max(2.0, self.s / 240.0)))
            soft = soft.resize((self.w, self.h), Image.Resampling.BICUBIC)
            # 柔光层作为背景光带垫在主线之下
            sa = soft.getchannel("A").point(lambda x: min(255, int(x * self.glow * 1.35)))
            soft.putalpha(sa)
            layer = Image.alpha_composite(soft, layer)
        elif self._spokes.getbbox() is not None:
            layer = Image.alpha_composite(layer, self._spokes)

        if self.glow <= 0:
            return layer

        # 局部辉光：较大半径模糊，形成柔和光环/渐变光核
        if self._halo.getbbox() is not None:
            sw, sh = max(2, self.w // 3), max(2, self.h // 3)
            glow_layer = self._halo.resize((sw, sh), Image.Resampling.BILINEAR)
            glow_layer = glow_layer.filter(
                ImageFilter.GaussianBlur(radius=max(2.0, self.s / 200.0)))
            glow_layer = glow_layer.resize((self.w, self.h), Image.Resampling.BICUBIC)
            ga = glow_layer.getchannel("A").point(
                lambda x: min(255, int(x * self.glow * 1.25)))
            glow_layer.putalpha(ga)
            layer = Image.alpha_composite(glow_layer, layer)

        # 全局柔光：整幅画面统一轻微模糊叠加
        sw, sh = max(2, self.w // 3), max(2, self.h // 3)
        halo = layer.resize((sw, sh), Image.Resampling.BILINEAR)
        halo = halo.filter(ImageFilter.GaussianBlur(radius=max(1.0, self.s / 420.0)))
        halo = halo.resize((self.w, self.h), Image.Resampling.BICUBIC)
        factor = self.glow * (1.15 if self.mode in ("circle", "dual_ring", "spiral") else 1.0)
        a = halo.getchannel("A").point(lambda x: min(255, int(x * factor)))
        halo.putalpha(a)
        return Image.alpha_composite(halo, layer)

    @staticmethod
    @lru_cache(maxsize=16)
    def _radial_mask(size: int, power: float) -> Image.Image:
        """生成正圆形径向渐变蒙版（中心 255 → 边缘 0），带缓存。"""
        ax = np.linspace(-1.0, 1.0, size, dtype=np.float32)
        r = np.sqrt(ax[:, None] ** 2 + ax[None, :] ** 2)
        v = np.clip(1.0 - r, 0.0, 1.0) ** power
        return Image.fromarray((v * 255).astype(np.uint8), mode="L")

    def _soft_orb(
        self, cx: float, cy: float, radius: float, rgba: tuple[int, int, int, int],
        power: float = 1.6, layer: Image.Image | None = None,
    ) -> None:
        """绘制正圆形径向渐变光球：中心亮、边缘平滑淡出。默认画到局部辉光层。"""
        if radius < 2:
            return
        mask = self._radial_mask(128, power)
        mask = mask.point(lambda x: int(x * rgba[3] / 255))
        orb = Image.new("RGBA", mask.size, rgba[:3] + (0,))
        orb.putalpha(mask)
        orb = orb.resize((max(2, int(radius * 2)), max(2, int(radius * 2))),
                         Image.Resampling.BILINEAR)
        target = layer if layer is not None else self._halo
        target.alpha_composite(orb, (int(cx - radius), int(cy - radius)))

    @staticmethod
    def _dim(rgba: tuple[int, int, int, int], scale: float) -> tuple[int, int, int, int]:
        r, g, b, a = rgba
        return (r, g, b, int(max(0, min(255, round(a * scale)))))

    def _stroke(
        self,
        d: ImageDraw.ImageDraw,
        draw_fn,
        rgba: tuple[int, int, int, int],
        width: int,
        soft_scale: float = 0.85,
        main_scale: float = 0.6,
        soft_width: int | None = None,
    ) -> None:
        """通用柔化描边：柔光光带画到 _spokes，主线降低权重画到主图层。"""
        if self.glow > 0:
            draw_fn(self._spokes_draw, self._dim(rgba, soft_scale), soft_width or width)
            draw_fn(d, self._dim(rgba, main_scale), width)
        else:
            draw_fn(d, rgba, width)

    def _glow_line(
        self, d, seg, rgba, width=1,
        soft_scale=0.85, main_scale=0.6, soft_width=None,
    ) -> None:
        self._stroke(
            d, lambda t, col, w: t.line(seg, fill=col, width=w),
            rgba, width, soft_scale, main_scale, soft_width,
        )

    def _glow_arc(
        self, d, box, start, end, rgba, width=1,
        soft_scale=0.85, main_scale=0.6, soft_width=None,
    ) -> None:
        self._stroke(
            d, lambda t, col, w: t.arc(box, start, end, fill=col, width=w),
            rgba, width, soft_scale, main_scale, soft_width,
        )

    def _glow_ellipse_outline(
        self, d, box, rgba, width=1,
        soft_scale=0.85, main_scale=0.6, soft_width=None,
    ) -> None:
        self._stroke(
            d, lambda t, col, w: t.ellipse(box, outline=col, width=w),
            rgba, width, soft_scale, main_scale, soft_width,
        )

    def _glow_polyline(
        self, d, pts, rgba, width=1,
        soft_scale=0.85, main_scale=0.6, soft_width=None,
    ) -> None:
        self._stroke(
            d, lambda t, col, w: t.line(pts, fill=col, width=w, joint="curve"),
            rgba, width, soft_scale, main_scale, soft_width,
        )

    @staticmethod
    @lru_cache(maxsize=512)
    def _vbar_mask(width: int, height: int) -> Image.Image:
        """单根渐变竖线的透明度蒙版：横向中间亮两侧淡出，纵向两端淡出。"""
        w, h = max(1, int(width)), max(2, int(height))
        # 用像素中心采样，保证 1px 宽也有非零中心值
        xs = ((np.arange(w, dtype=np.float32) + 0.5) / w) * 2.0 - 1.0
        hp = np.clip(1.0 - xs * xs, 0.0, 1.0) ** 1.2
        ys = (np.arange(h, dtype=np.float32) + 0.5) / h
        # 顶部淡入较长，底部只留极短淡出，保持频谱条"立"在地平线上
        vp = np.clip(ys / 0.28, 0.0, 1.0) ** 0.8
        vp *= np.clip((1.0 - ys) / 0.06, 0.0, 1.0) ** 0.5
        return Image.fromarray((hp[None, :] * vp[:, None] * 255).astype(np.uint8), mode="L")

    def _soft_vbar(
        self, cx: float, y0: float, y1: float, bar_width: float,
        rgba: tuple[int, int, int, int],
    ) -> None:
        """绘制一根独立渐变竖线到 _bars 层，条与条之间保留间隙。"""
        w = max(1, int(round(bar_width)))
        h = max(2, int(round((y1 - y0) / 4.0)) * 4)
        mask = self._vbar_mask(w, h)
        peak = int(min(255, rgba[3] * 1.18))
        alpha = mask.point(lambda x: int(x * peak / 255))
        sprite = Image.new("RGBA", (w, h), rgba[:3] + (0,))
        sprite.putalpha(alpha)
        self._bars.alpha_composite(sprite, (int(round(cx - w / 2)), int(round(y0))))

    def _soft_ring(
        self, cx: float, cy: float, r: float,
        rgba: tuple[int, int, int, int], width: float,
        arc: tuple[int, int] | None = None,
    ) -> None:
        """绘制径向渐变圆环：多层 1px 同心细环按高斯权重叠加，边缘平滑淡出。"""
        if r < 2 or width <= 0:
            return
        # 较大的 sigma 让相邻细环亮度接近，避免出现"一根亮线 + 光晕"的硬核感
        sigma = max(1.2, width * 0.85)
        span = max(2, int(math.ceil(width * 1.8)))
        cr, cg, cb, ca = rgba
        for k in range(-span, span + 1):
            rr = r + k
            if rr < 1:
                continue
            a = ca * math.exp(-0.5 * (k / sigma) ** 2)
            if a < 2:
                continue
            col = (cr, cg, cb, int(min(255, a)))
            box = [cx - rr, cy - rr, cx + rr, cy + rr]
            if arc is None:
                self._rings_draw.ellipse(box, outline=col, width=1)
            else:
                self._rings_draw.arc(box, arc[0], arc[1], fill=col, width=1)

    # ------------------------------ 效果 ------------------------------
    def _draw_bottom(self, d: ImageDraw.ImageDraw, f: FrameFeatures) -> None:
        n = len(f.bars)
        bw = self.w / n
        line_w = max(1.0, bw * 0.6)   # 只占 60% 节距，条间留空
        for i, v in enumerate(f.bars):
            if v < 0.015:
                continue
            bh = float(v) * self.h * 0.76
            self._soft_vbar(
                (i + 0.5) * bw, self.h - bh, self.h, line_w,
                self.color(i / n, v, x=i / n),
            )
        w = max(2, int(self.s * 0.003))
        self._glow_line(
            d, [(0, self.h - 1), (self.w, self.h - 1)],
            self.color(0.5, f.level, 100 + 120 * f.level, x=0.5),
            width=w, soft_scale=0.7, main_scale=0.7,
        )

    def _draw_mirror(self, d: ImageDraw.ImageDraw, f: FrameFeatures) -> None:
        n = len(f.bars)
        count = min(n, 160)
        cx, cy = self.w / 2, self.h / 2
        span = self.w * 0.475
        bw = span / count
        line_w = max(1.0, bw * 0.6)
        for i in range(count):
            v = float(f.bars[int(i / count * n)])
            if v < 0.012:
                continue
            bh = v * self.h * 0.44
            off = (i + 0.5) * bw
            col_l = self.color(i / count, v, x=max(0.0, (cx - off) / self.w))
            col_r = self.color(i / count, v, x=min(1.0, (cx + off) / self.w))
            self._soft_vbar(cx - off, cy - bh, cy + bh, line_w, col_l)
            self._soft_vbar(cx + off, cy - bh, cy + bh, line_w, col_r)
        self._glow_line(
            d, [(0, cy), (self.w, cy)],
            self.color(0.7, f.level, 90 + 130 * f.level, x=0.5),
            width=max(2, int(self.s * 0.003)), soft_scale=0.7, main_scale=0.7,
        )

    def _draw_circle(self, d: ImageDraw.ImageDraw, f: FrameFeatures) -> None:
        n = len(f.bars)
        cx, cy = self.w / 2, self.h / 2
        base = self.s * 0.22
        count = 360 if self.s >= 800 else 180
        width = max(1, int(self.s * 0.0025))
        for i in range(count):
            v = float(f.bars[int(i / count * n)])
            if v < 0.014:
                continue
            ang = 2 * math.pi * i / count - math.pi / 2
            ca, sa = math.cos(ang), math.sin(ang)
            outer = base + v * self.s * 0.27
            seg = [(cx + ca * base, cy + sa * base), (cx + ca * outer, cy + sa * outer)]
            col = self.color(i / count, v, x=0.5 + 0.5 * ca)
            self._spokes_draw.line(seg, fill=col, width=width)
            # 主线降低不透明度：让柔化光带与主线亮度更接近，缩小中心-边缘落差
            d.line(seg, fill=self.color(i / count, v, (90 + 165 * v) * 0.42, x=0.5 + 0.5 * ca),
                   width=max(1, int(width * 0.8)))
        r = base * (0.87 + 0.07 * f.pulse)
        ring_a = 22 + 42 * f.bass
        # 圆环压低亮度，仅作为径向短线的低调结构底纹，避免比短线还亮而刺眼
        self._soft_ring(
            cx, cy, r, self.color(0.5, f.bass, ring_a, x=0.5),
            width=max(2, int(self.s * 0.0045)),
        )

    def _draw_dual_ring(self, d: ImageDraw.ImageDraw, f: FrameFeatures) -> None:
        n = len(f.bars)
        cx, cy = self.w / 2, self.h / 2
        r1, r2 = self.s * 0.16, self.s * 0.31
        count = 240 if self.s >= 800 else 160
        spin = self._time
        width = max(1, int(self.s * 0.0022))
        # 两个渐变基准圆环：大幅压低亮度，仅作为径向短线的低调结构底纹，
        # 避免圆环比短线还亮造成反差刺眼（alpha 约 30-45，远低于短线的 45-107）。
        for r, p, a in ((r1, 0.25, 0.35 + 0.25 * f.bass), (r2, 0.75, 0.30 + 0.25 * f.mid)):
            self._soft_ring(
                cx, cy, r, self.color(p, a, 20 + 42 * a),
                width=max(2, int(self.s * 0.0045)),
            )
        for i in range(count):
            v = float(f.bars[int(i / count * n)])
            if v < 0.012:
                continue
            a1 = 2 * math.pi * i / count + spin * 0.45
            a2 = -2 * math.pi * i / count - spin * 0.28 + math.pi / count
            for ang, r0, span, col_p in ((a1, r1, 0.13, i / count), (a2, r2, 0.19, 1 - i / count)):
                ca, sa = math.cos(ang), math.sin(ang)
                outer = r0 + v * self.s * span
                seg = [(cx + ca * r0, cy + sa * r0), (cx + ca * outer, cy + sa * outer)]
                self._spokes_draw.line(seg, fill=self.color(col_p, v, x=0.5 + 0.5 * ca), width=width)
                d.line(seg, fill=self.color(col_p, v, (90 + 165 * v) * 0.42, x=0.5 + 0.5 * ca),
                       width=max(1, int(width * 0.8)))
            if v > 0.55 and i % 4 == 0:
                self._spokes_draw.line(
                    [(cx + math.cos(a1) * r1, cy + math.sin(a1) * r1),
                     (cx + math.cos(a1) * r2, cy + math.sin(a1) * r2)],
                    fill=self.color(i / count, v, 70, x=0.5 + 0.5 * math.cos(a1)), width=1)

    def _draw_spiral(self, d: ImageDraw.ImageDraw, f: FrameFeatures) -> None:
        n = len(f.bars)
        cx, cy = self.w / 2, self.h / 2
        arms = 3
        width = max(2, int(self.s * 0.0032))
        for arm in range(arms):
            for i, v_raw in enumerate(f.bars):
                v = float(v_raw)
                if v < 0.012:
                    continue
                ang = i * 0.155 + arm * 2 * math.pi / arms + self._time * 0.55
                r = self.s * 0.045 + i / n * self.s * 0.40
                tip = r + v * self.s * 0.085
                ca, sa = math.cos(ang), math.sin(ang)
                seg = [(cx + ca * r, cy + sa * r), (cx + ca * tip, cy + sa * tip)]
                self._spokes_draw.line(seg, fill=self.color(i / n, v, x=0.5 + 0.5 * ca), width=width)
                d.line(seg, fill=self.color(i / n, v, (90 + 165 * v) * 0.42, x=0.5 + 0.5 * ca),
                       width=max(1, int(width * 0.8)))
        core = self.s * 0.035 * (1 + f.pulse * 0.8)
        d.ellipse([cx - core, cy - core, cx + core, cy + core],
                  fill=self.color(0.5, 1.0, 170 + 80 * f.pulse, x=0.5))
        # 中心核辉光
        self._soft_orb(cx, cy, core * 1.9,
                       self.color(0.5, 1.0, 110, x=0.5))

    def _draw_waveform(self, d: ImageDraw.ImageDraw, f: FrameFeatures) -> None:
        n = len(f.bars)
        cx, cy = self.w / 2, self.h / 2
        bw = self.w / n
        line_w = max(1.0, bw * 0.6)
        for i, v in enumerate(f.bars):
            if v < 0.02:
                continue
            bh = v * self.h * 0.30
            self._soft_vbar(
                (i + 0.5) * bw, cy - bh, cy + bh, line_w,
                self.color(i / n, v, 45 + 90 * v, x=i / n),
            )
        wave = f.wave
        amp = self.h * 0.30 * (0.5 + f.level)
        pts = [
            (j / (len(wave) - 1) * self.w, cy + float(wave[j]) * amp)
            for j in range(len(wave))
        ]
        # 波形曲线压低亮度：主曲线 alpha 240->70、镜像 110->45，
        # 让背景频谱竖条成为主体，避免曲线过亮盖过频谱、显得刺眼。
        self._glow_polyline(
            d, pts,
            self.color(0.65, max(0.4, f.level), 70, x=0.65),
            width=max(2, int(self.s * 0.0035)), soft_scale=0.9, main_scale=0.6,
        )
        self._glow_polyline(
            d, [(x, self.h - y) for x, y in pts],
            self.color(0.2, f.level, 45, x=0.2),
            width=max(1, int(self.s * 0.0018)), soft_scale=0.6, main_scale=0.75,
        )

    def _draw_tunnel(self, d: ImageDraw.ImageDraw, f: FrameFeatures) -> None:
        """指数透视环 + 向外涌动：远处密、近处疏，营造穿越隧道的纵深感。"""
        n = len(f.bars)
        cx, cy = self.w / 2, self.h / 2
        rings = 30 if self.s >= 800 else 22
        r_min, r_max = self.s * 0.032, self.s * 0.56
        ratio = r_max / r_min
        flow = (self._time * 0.16) % 1.0

        radii: list[float] = []
        for i in range(rings):
            p = i / rings                       # 固定频段，随圆环一起向外流动
            t = (p + flow) % 1.0                # 当前透视深度：0=远处 1=近处
            r = r_min * ratio ** t
            fade = min(1.0, t / 0.10, (1.0 - t) / 0.16)   # 两端淡入淡出，隐藏循环跳变
            v = float(f.bars[int(p * n) % n])
            alpha = (60 + 155 * v) * fade * (0.65 + 0.35 * t)
            width = max(1, int(self.s * (0.0013 + 0.0024 * v) * (0.7 + 0.6 * t)))
            # 左右半环分别取色，兼容紫蓝渐变（左紫右蓝）
            # 每个透视环本身用多层同心细环做径向渐变，边缘平滑淡出
            self._soft_ring(
                cx, cy, r, self.color(p, v, alpha, x=0.80),
                width=max(2, width), arc=(270, 90),
            )
            self._soft_ring(
                cx, cy, r, self.color(p, v, alpha, x=0.20),
                width=max(2, width), arc=(90, 270),
            )
            radii.append(r)

        # 断续能量放射线：只在强频段出现，避免完整网格感
        spokes = 48 if self.s >= 800 else 36
        spin = self._time * 0.07
        for j in range(spokes):
            p = j / spokes
            v = float(f.bars[int(p * n) % n])
            if v < 0.16:
                continue
            ang = 2 * math.pi * p + spin
            ca, sa = math.cos(ang), math.sin(ang)
            col = self.color(p, v, 28 + 70 * v, x=0.5 + 0.5 * ca)
            for k in range(3, rings - 4, 6):
                r0 = radii[(k + int(flow * rings)) % rings]
                r1 = radii[(k + 3 + int(flow * rings)) % rings]
                if r1 <= r0:
                    continue
                self._glow_line(
                    d,
                    [(cx + ca * r0, cy + sa * r0), (cx + ca * r1, cy + sa * r1)],
                    col, width=1, soft_scale=0.6, main_scale=0.75,
                )

        # 中心能量核：整体改为渐变光球，随节拍呼吸且边缘完全柔化
        core = self.s * 0.011 * (1 + 0.5 * f.pulse)
        self._soft_orb(
            cx, cy, core * 2.4,
            self.color(0.5, 1.0, 170 + 60 * f.pulse, x=0.5),
            power=2.2, layer=self._core,
        )
        self._soft_orb(cx, cy, self.s * (0.05 + 0.02 * f.pulse),
                       self.color(0.5, 1.0, 150, x=0.5))

    def _draw_particles(self, d: ImageDraw.ImageDraw, f: FrameFeatures) -> None:
        cx, cy = self.w / 2, self.h / 2
        if f.beat:
            for _ in range(70):
                ang = self.rng.uniform(0, 2 * math.pi)
                speed = self.s * self.rng.uniform(0.002, 0.011) * (0.8 + f.bass)
                self.particles.append({
                    "x": cx, "y": cy, "vx": math.cos(ang) * speed, "vy": math.sin(ang) * speed,
                    "life": 1.0, "decay": self.rng.uniform(0.005, 0.012),
                    "size": self.s * self.rng.uniform(0.003, 0.009),
                    "p": self.rng.random(), "v": 1.0,
                })
        for _ in range(20):
            i = self.rng.randrange(len(f.bars))
            v = float(f.bars[i])
            if v < 0.06:
                continue
            ang = 2 * math.pi * i / len(f.bars) - math.pi / 2
            r = self.s * self.rng.uniform(0.10, 0.20)
            self.particles.append({
                "x": cx + math.cos(ang) * r, "y": cy + math.sin(ang) * r,
                "vx": math.cos(ang) * self.s * 0.005 * v, "vy": math.sin(ang) * self.s * 0.005 * v,
                "life": 1.0, "decay": self.rng.uniform(0.006, 0.011),
                "size": self.s * 0.006 * v,
                "p": i / len(f.bars), "v": v,
            })
        alive: list[dict] = []
        for p in self.particles:
            p["x"] += p["vx"]
            p["y"] += p["vy"]
            p["vx"] *= 0.985
            p["vy"] *= 0.985
            p["vy"] += self.s * 0.00008
            p["life"] -= p["decay"]
            if p["life"] <= 0:
                continue
            alive.append(p)
            size = p["size"] * (0.4 + p["life"])
            d.ellipse(
                [p["x"] - size, p["y"] - size, p["x"] + size, p["y"] + size],
                fill=self.color(p["p"], p["v"], 220 * p["life"], x=p["x"] / self.w),
            )
        self.particles = alive[-900:]
        core = self.s * 0.075 * (1 + 0.5 * f.pulse)
        for ring, radius in enumerate((0.13, 0.23, 0.33)):
            r = self.s * radius * (1 + 0.06 * f.pulse)
            box = [cx - r, cy - r, cx + r, cy + r]
            ring_alpha = 40 + 90 * f.level
            self._glow_ellipse_outline(
                d, box, self.color(ring / 3, f.mid, ring_alpha, x=ring / 3),
                width=max(1, int(self.s * 0.002)), soft_scale=0.6, main_scale=0.7,
            )
            # 局部辉光：粗环模糊成光环
            self._halo_draw.ellipse(
                box, outline=self.color(ring / 3, f.mid, ring_alpha * 0.85, x=ring / 3),
                width=max(3, int(self.s * 0.006)))
        for i in range(0, len(f.bars), 3):
            v = float(f.bars[i])
            if v < 0.06:
                continue
            ang = 2 * math.pi * i / len(f.bars) - math.pi / 2
            self._glow_line(
                d,
                [(cx + math.cos(ang) * core, cy + math.sin(ang) * core),
                 (cx + math.cos(ang) * (core + v * self.s * 0.26), cy + math.sin(ang) * (core + v * self.s * 0.26))],
                self.color(i / len(f.bars), v, x=0.5 + 0.5 * math.cos(ang)),
                width=max(1, int(self.s * 0.002)),
                soft_scale=0.65, main_scale=0.75,
            )
        # 能量核：整个核心区域都是径向渐变光球（无硬边），随音乐缩放
        core_col = self.color(0.5, f.bass, 205 + 25 * f.bass, x=0.5)
        self._soft_orb(cx, cy, core * 1.7, core_col, power=2.4, layer=self._core)
        # 外围柔光晕（画到辉光层，模糊后更柔和）
        self._soft_orb(cx, cy, core * 2.3,
                       self.color(0.5, f.bass, 150, x=0.5), power=2.2)
