# utils/ai_analysis.py

import os
from dotenv import load_dotenv
import openai

# טען מפתח API
load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")


def analyze_with_ai(data: dict) -> dict:
    """
    ניתוח GPT על סמך RSI, ADX, תבנית, מגמה ונפח.
    """
    if not openai.api_key:
        return {"error": "מפתח OpenAI לא מוגדר"}

    if not data or not isinstance(data, dict):
        return {"error": "Invalid or empty input data"}

    prompt = f"""
    הנתונים הטכניים:
    - RSI: {data.get("rsi")}
    - ADX: {data.get("adx")}
    - מגמה: {data.get("trend")}
    - תבנית גרף: {data.get("pattern")}
    - נפח מסחר: {data.get("volume")}

    האם כדאי להיכנס לעסקת לונג או שורט? נתח בקצרה וכתוב המלצה.
    """

    try:
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=300
        )
        result = response.choices[0].message.content.strip()
        return {"analysis": result}
    except Exception as e:
        return {"error": f"שגיאה בניתוח GPT: {e}"}


def predict_optimal_sl_tp(symbol: str, price: float, direction: str, atr: float = None) -> dict:
    """
    חיזוי SL/TP חכם לפי כיוון ומחיר, כולל ATR אם קיים.
    """
    try:
        direction = direction.upper()
        if direction not in {"LONG", "SHORT"}:
            raise ValueError("כיוון לא חוקי: נדרש 'LONG' או 'SHORT'")

        # חישוב מבוסס ATR אם קיים
        if atr and atr > 0:
            sl = price - atr if direction == "LONG" else price + atr
            tp = price + atr * 1.5 if direction == "LONG" else price - atr * 1.5
        else:
            # ברירת מחדל לפי אחוזים
            sl_pct = 0.01
            tp_pct = 0.015
            sl = price * (1 - sl_pct) if direction == "LONG" else price * (1 + sl_pct)
            tp = price * (1 + tp_pct) if direction == "LONG" else price * (1 - tp_pct)

        # הגנה על מרחק SL/TP מינימלי (לפחות 0.5%)
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
        return {"error": f"שגיאה בחיזוי SL/TP: {e}"}





