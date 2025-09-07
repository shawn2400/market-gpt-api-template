# utils/generate_logo.py
import os
from typing import Optional
from PIL import Image, ImageDraw, ImageFont, ImageFilter

def _ensure_static(path: str = "static") -> None:
    os.makedirs(path, exist_ok=True)

def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in ("arial.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(candidate, size)
        except Exception:
            continue
    return ImageFont.load_default()

def _text_bbox(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont):
    try:
        x0, y0, x1, y1 = draw.textbbox((0, 0), text, font=font)
    except Exception:
        w, h = draw.textsize(text, font=font)
        x0, y0, x1, y1 = 0, 0, w, h
    return (x0, y0, x1, y1)

def generate_logo(
    text: str = "AlgoGPT",
    filename: str = "static/logo.png",
    *,
    size: int = 512,
    dark_bg: bool = True,
    transparent: bool = False,
    add_glow: bool = True,
) -> str:
    """
    מייצר לוגו PNG + ICO + SVG.
    """
    _ensure_static(os.path.dirname(filename) or "static")

    bg = (30, 30, 30, 0 if transparent else 255) if dark_bg else (238, 238, 238, 0 if transparent else 255)
    fg = (255, 255, 255, 255) if dark_bg else (15, 15, 15, 255)

    mode = "RGBA" if transparent else "RGB"
    img = Image.new(mode, (size, size), bg)
    draw = ImageDraw.Draw(img)

    font = _load_font(max(24, int(size * 0.18)))
    x0, y0, x1, y1 = _text_bbox(draw, text, font)
    tw, th = (x1 - x0), (y1 - y0)
    tx = (size - tw) // 2
    ty = (size - th) // 2

    if add_glow:
        glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        gdraw = ImageDraw.Draw(glow)
        gdraw.text((tx, ty), text, font=font, fill=(fg[0], fg[1], fg[2], 220))
        for r in (4, 10, 18):
            glow = glow.filter(ImageFilter.GaussianBlur(radius=r))
        img = Image.alpha_composite(img.convert("RGBA"), glow)

    draw = ImageDraw.Draw(img)
    draw.text((tx, ty), text, font=font, fill=fg)

    img.save(filename, optimize=True)

    # ICO
    base_no_ext, _ = os.path.splitext(filename)
    try:
        img.convert("RGBA").resize((256, 256)).save(f"{base_no_ext}.ico", format="ICO", sizes=[(256, 256)])
    except Exception:
        pass

    # SVG
    try:
        svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}">
  <rect width="100%" height="100%" fill="{'none' if transparent else ('#1e1e1e' if dark_bg else '#eeeeee')}" />
  <text x="50%" y="50%" dominant-baseline="middle" text-anchor="middle"
        font-family="DejaVu Sans, Arial, sans-serif" font-weight="700"
        font-size="{int(size*0.18)}" fill="{('#ffffff' if dark_bg else '#0f0f0f')}">{text}</text>
</svg>"""
        with open(f"{base_no_ext}.svg", "w", encoding="utf-8") as f:
            f.write(svg)
    except Exception:
        pass

    return filename



