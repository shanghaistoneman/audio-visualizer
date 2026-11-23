"""生成参数示例图库：效果 × 配色、效果 × 柱数、效果 × 发光强度。

运行: python -m audio_visualizer.generate_gallery
输出目录: 示例图库/
"""
from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFont

from .demo import render_demo_preview
from .effects import BAR_OPTIONS, GLOW_OPTIONS, MODE_NAMES, MODES, THEMES

THUMB_W, THUMB_H = 480, 270
SHEET_W, SHEET_H = 240, 135
ROW_H = SHEET_H + 22
BG = (14, 14, 20, 255)


def font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf"):
        if os.path.isfile(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                pass
    return ImageFont.load_default()


def save_preview(img: Image.Image, path: str, label: str) -> None:
    img.save(path)
    # 同时生成一张带深色底的小图，便于在资源管理器里直接查看
    composite = Image.alpha_composite(Image.new("RGBA", img.size, BG), img).convert("RGB")
    d = ImageDraw.Draw(composite)
    d.rectangle([0, 0, img.width, 26], fill=(0, 0, 0))
    d.text((8, 5), label, fill=(235, 235, 245), font=font(15))
    composite.save(os.path.splitext(path)[0] + "_预览.jpg", quality=90)


def build_sheet(
    path: str,
    cols: list[str],
    col_label: str,
    fixed_bars: int = 96,
    fixed_glow: float = 1.0,
    fixed_theme: str = "neon",
) -> None:
    sheet = Image.new(
        "RGB", (len(cols) * SHEET_W, len(MODES) * ROW_H + 30), (22, 22, 30)
    )
    d = ImageDraw.Draw(sheet)
    d.text((8, 6), f"效果总览 - {col_label}", fill=(255, 255, 255), font=font(17))
    for c, col in enumerate(cols):
        caption = THEMES[col] if col_label == "配色" else str(col)
        d.text((c * SHEET_W + 8, len(MODES) * ROW_H + 6), caption,
               fill=(200, 200, 215), font=font(13))
    for r, mode in enumerate(MODES):
        y0 = 30 + r * ROW_H
        d.text((8, y0 + 2), MODE_NAMES[mode], fill=(170, 200, 255), font=font(13))
        for c, col in enumerate(cols):
            if col_label == "配色":
                kw = dict(mode=mode, theme=col, bars=fixed_bars, glow=fixed_glow)
            elif col_label == "柱数":
                kw = dict(mode=mode, theme=fixed_theme, bars=int(col), glow=fixed_glow)
            else:
                kw = dict(mode=mode, theme=fixed_theme, bars=fixed_bars, glow=float(col))
            img = render_demo_preview(**kw, width=SHEET_W * 2, height=SHEET_H * 2)
            thumb = img.resize((SHEET_W, SHEET_H), Image.Resampling.LANCZOS)
            thumb = Image.alpha_composite(Image.new("RGBA", thumb.size, BG), thumb).convert("RGB")
            sheet.paste(thumb, (c * SHEET_W, y0 + 20))
    sheet.save(path, quality=92)


def main() -> None:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = os.path.join(root, "示例图库")
    os.makedirs(out, exist_ok=True)

    total = 0
    for mode in MODES:
        for theme in THEMES:
            img = render_demo_preview(mode, theme, 96, 1.0, THUMB_W, THUMB_H)
            path = os.path.join(out, f"效果_{mode}_配色_{theme}.png")
            save_preview(img, path, f"{MODE_NAMES[mode]} / {THEMES[theme]} / 柱数 96 / 发光 1.0")
            total += 1
        for bars in BAR_OPTIONS:
            img = render_demo_preview(mode, "neon", bars, 1.0, THUMB_W, THUMB_H)
            path = os.path.join(out, f"柱数_{mode}_{bars}.png")
            save_preview(img, path, f"{MODE_NAMES[mode]} / 霓虹青紫 / 柱数 {bars} / 发光 1.0")
            total += 1
        for glow in GLOW_OPTIONS:
            img = render_demo_preview(mode, "neon", 96, glow, THUMB_W, THUMB_H)
            path = os.path.join(out, f"发光_{mode}_{glow}.png")
            save_preview(img, path, f"{MODE_NAMES[mode]} / 霓虹青紫 / 柱数 96 / 发光 {glow}")
            total += 1
        print(f"已生成 {mode} 的示例图")

    build_sheet(os.path.join(out, "总览_配色.png"), list(THEMES), "配色")
    build_sheet(os.path.join(out, "总览_柱数.png"), [str(b) for b in BAR_OPTIONS], "柱数")
    build_sheet(os.path.join(out, "总览_发光.png"), [str(g) for g in GLOW_OPTIONS], "发光")
    print(f"完成：{total} 张示例图 + 3 张总览图 -> {out}")


if __name__ == "__main__":
    main()
