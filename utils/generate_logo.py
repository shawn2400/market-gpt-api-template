# utils/generate_logo.py
from __future__ import annotations

import os
from datetime import datetime
from typing import Optional, Tuple

# Pillow עובד מצוין גם בסביבות headless
from PIL import Image, ImageDraw, ImageFont, ImageFilter


def _find_font(candidates: Tuple[str, ...] = (
    # סדר עדיפויות: DejaVu (נפוץ בלינוקס), Arial (אם קיים), LiberationSans
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "arial.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
)) -> Optional[str]:
    for p in candidates:
        if os.path.exists(p):
            return p
    return None


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    fp = _find_font()
    if fp:
        try:
            return ImageFont.truetype(fp, size)
        except Exception:
            pass
    # פולי־בק
    return ImageFont.load_default()


def generate_logo(
    text: str = "AlgoGPT",
    filename: str = "static/logo.png",
    size: int = 512,
    dark_bg: bool = True,
    transparent: bool = False,
    add_glow: bool = True,
) -> str:
    """
    מייצר לוגו טקסטואלי נקי עם צל/זוהר קל. יוצר גם גרסאות ICO/SVG אם ביקשתם בשם הקובץ.
    :return: הנתיב הסופי של קובץ ה-PNG.
    """
    os.makedirs(os.path.dirname(filename) or ".", exist_ok=True)

    W = H = max(128, int(size))
    mode = "RGBA" if transparent else "RGB"
    bg_color = (0, 0, 0, 0) if transparent else ((24, 24, 28) if dark_bg else (245, 245, 245))
    fg_color = (255, 255, 255) if dark_bg or transparent else (20, 20, 20)
    accent = (0, 200, 255)  # קו תחתון עדין

    # קנבס
    img = Image.new(mode, (W, H), bg_color)
    draw = ImageDraw.Draw(img)

    # טקסט — גודל פונט דינמי יחסית
    font = _load_font(int(W * 0.20))
    # textbbox זמין מפילו 8.0; נמנע משבר ישן ונופל ל-getsize במידת הצורך
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    except Exception:
        tw, th = draw.textsize(text, font=font)

    tx = (W - tw) // 2
    ty = (H - th) // 2

    # זוהר רך
    if add_glow:
        glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        gdraw = ImageDraw.Draw(glow)
        for r, a in ((2, 60), (4, 40), (6, 25)):
            gdraw.text((tx, ty), text, font=font, fill=(accent[0], accent[1], accent[2], a))
            glow = glow.filter(ImageFilter.GaussianBlur(radius=r))
        img = Image.alpha_composite(img.convert("RGBA"), glow) if img.mode != "RGBA" else Image.alpha_composite(img, glow)

    # טקסט
    draw = ImageDraw.Draw(img)
    draw.text((tx, ty), text, font=font, fill=fg_color)

    # קו תחתון מינימליסטי
    underline_y = int(ty + th + H * 0.04)
    if underline_y < H - 10:
        pad = int(W * 0.10)
        draw.line([(pad, underline_y), (W - pad, underline_y)], width=max(2, W // 160), fill=accent)

    # חותמת זמן בשם אם מבקשים לשמור גרסאות
    out_png = filename if filename.lower().endswith(".png") else os.path.splitext(filename)[0] + ".png"
    img.save(out_png, optimize=True)

    # גרסת ICO קטנה לאייקונים (אופציונלי)
    out_ico = os.path.splitext(out_png)[0] + ".ico"
    try:
        img_ico = img.convert("RGBA").resize((256, 256), Image.LANCZOS)
        img_ico.save(out_ico, sizes=[(256, 256), (128, 128), (64, 64), (32, 32), (16, 16)])
    except Exception:
        pass

    # גרסת SVG טקסטואלית (אופציונלי — לא תלויה בפונט מותקן בדפדפן)
    out_svg = os.path.splitext(out_png)[0] + ".svg"
    try:
        # נשרטט מלבן רקע אם לא שקוף
        svg_bg = "" if transparent else f'<rect width="100%" height="100%" fill="rgb{bg_color[:3]}"/>'
        svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">
{svg_bg}
<text x="50%" y="50%" dominant-baseline="middle" text-anchor="middle"
      font-family="DejaVu Sans, Arial, sans-serif" font-size="{int(W*0.20)}"
      fill="rgb{fg_color if isinstance(fg_color, tuple) else (255,255,255)}">{text}</text>
<line x1="{int(W*0.10)}" y1="{underline_y}" x2="{int(W*0.90)}" y2="{underline_y}"
      stroke="rgb{accent}" stroke-width="{max(2, W // 160)}"/>
</svg>"""
        with open(out_svg, "w", encoding="utf-8") as f:
            f.write(svg)
    except Exception:
        pass

    print(f"✅ הלוגו נשמר: {out_png}")
    return out_png


if __name__ == "__main__":
    # הפקה מהירה כברירת מחדל
    os.makedirs("static", exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    generate_logo(text="AlgoGPT", filename=f"static/logo_{ts}.png", size=512, dark_bg=True, transparent=False)

