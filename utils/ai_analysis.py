# utils/ai_analysis.py

import os
import openai
from dotenv import load_dotenv

# טען מפתחות
load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")

def analyze_with_ai(data: dict) -> dict:
    """
    ניתוח GPT על סמך RSI, ADX, מגמה, תבנית ונפח.
    מחזיר טקסט המלצה עם סיכום ניתוח.
    """
    if not openai.api_key:
        return {"error": "⚠️ מפתח OpenAI לא מוגדר"}

    if not data or not isinstance(data, dict):
        return {"error": "⚠️ קלט לא תקין"}

    prompt = f"""
    ניתוח טכני לפי נתונים:
    - RSI: {data.get("rsi")}
    - ADX: {data.get("adx")}
    - מגמה: {data.get("trend")}
    - תבנית גרף: {data.get("pattern")}
    - נפח מסחר: {data.get("volume")}

    בהסתמך על הנתונים, האם יש פוטנציאל ללונג או שורט? הסבר בקצרה מה מצביע על כך.
    """
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "אתה אנליסט טכני מנוסה בקריפטו. התשובה שלך צריכה להיות ישירה, תמציתית ומבוססת אינדיקטורים בלבד."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.5,
            max_tokens=300
        )
        content = response.choices[0].message.content.strip()
        return {"analysis": content}
    except Exception as e:
        return {"error": f"שגיאה בניתוח GPT: {str(e)}"}


def predict_optimal_sl_tp(symbol: str, price: float, direction: str, atr: float = None) -> dict:
    """
    חיזוי SL ו־TP חכם לפי כיוון, מחיר ו־ATR אם קיים.
    """
    try:
        direction = direction.upper()
        if direction not in ("LONG", "SHORT"):
            raise ValueError("כיוון לא חוקי (רק LONG או SHORT)")

        # ATR-based חישוב
        if atr and atr > 0:
            sl = price - atr if direction == "LONG" else price + atr
            tp = price + atr * 1.5 if direction == "LONG" else price - atr * 1.5
        else:
            # ברירת מחדל לפי אחוז
            sl = price * (0.99 if direction == "LONG" else 1.01)
            tp = price * (1.015 if direction == "LONG" else 0.985)

        # הגנה על מרחק מינימלי
        min_gap = price * 0.005
        if abs(tp - sl) < min_gap:
            adjust = price * 0.01
            sl = price - adjust if direction == "LONG" else price + adjust
            tp = price + adjust * 1.5 if direction == "LONG" else price - adjust * 1.5

        return {
            "sl": round(sl, 4),
            "tp": round(tp, 4)
        }

    except Exception as e:
        return {"error": f"שגיאה בחיזוי SL/TP: {str(e)}"}






