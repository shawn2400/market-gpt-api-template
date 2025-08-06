import os
from PIL import Image, ImageDraw, ImageFont

def generate_logo(text="AlgoGPT", filename="static/logo.png"):
    try:
        # הגדרות בסיסיות
        width, height = 512, 512
        background_color = (30, 30, 30)  # כהה
        text_color = (255, 255, 255)     # לבן

        # יצירת תיקייה אם לא קיימת
        os.makedirs("static", exist_ok=True)

        # יצירת תמונה
        img = Image.new("RGB", (width, height), background_color)
        draw = ImageDraw.Draw(img)

        # טעינת פונט – אם Arial לא זמין, השתמש בברירת מחדל
        try:
            font = ImageFont.truetype("arial.ttf", 72)
        except:
            font = ImageFont.load_default()

        # מיקום טקסט למרכז
        text_size = draw.textbbox((0, 0), text, font=font)
        text_width = text_size[2] - text_size[0]
        text_height = text_size[3] - text_size[1]
        text_x = (width - text_width) // 2
        text_y = (height - text_height) // 2

        # ציור הטקסט
        draw.text((text_x, text_y), text, font=font, fill=text_color)

        # שמירה
        img.save(filename)
        print(f"✅ הלוגו נשמר בהצלחה: {filename}")

    except Exception as e:
        print(f"❌ שגיאה ביצירת לוגו: {e}")

if __name__ == "__main__":
    generate_logo()
