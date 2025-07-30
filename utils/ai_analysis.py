# utils/ai_analysis.py

import os
import re
from dotenv import load_dotenv
import openai
from typing import Dict, Union
from utils.calculate_quantity import get_precision_info

load_dotenv()

# הגדרת המפתח למערכת GPT
openai.api_key = os.getenv("OPENAI_API_KEY")

def round_tick(value, tick):
    """עיגול ערך למחיר חוקי לפי tickSize (כלפי מטה)"""
    try:
        return round((value // tick) * tick, 6)
    except Exception:
        return round(value, 6)

def analyze_with_ai(data: Dict[str, Union[str, float]]) -> Dict[str, Union[str, float]]:
    """
    ניתוח GPT על סמך RSI, ADX, מגמה, תבנית ונפח.
    מחזיר טקסט המלצה + ניקוד.
    """
    if not openai.api_key:
        return {"error": "⚠️ מפתח OpenAI לא מוגדר"}

    required_fields = ["rsi", "adx", "trend", "pattern", "volume"]
    if not all(k in data for k in required_fields):
        return {"error": "⚠️ נתונים חסרים לניתוח AI"}

    prompt = f"""
    ניתוח טכני לפי הנתונים:
    - RSI: {data['rsi']}
    - ADX: {data['adx']}
    - מגמה: {data['trend']}
    - תבנית גרף: {data['pattern']}
    - נפח מסחר: {data['volume']}
    על סמך נתונים אלו בלבד – האם יש סבירות לטרייד LONG או SHORT?
    נא להסביר את המסקנה בקצרה ולדרג (0-10) את איכות הסט־אפ.
    """

    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "אתה אנליסט טכני מקצועי. תן תשובה עניינית ומנומקת – בלי ניחושים."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.4,
            max_tokens=250
        )
        content = response.choices[0].message["content"].strip()
        match = re.search(r"\b([0-9](?:\.\d{1,2})?)\b\s*/\s*10\b", content)
        score = float(match.group(1)) if match else 0.9
        return {
            "answer": content,
            "score": score
        }

    except Exception as e:
        return {"error": f"שגיאת GPT: {type(e).__name__} – {e}"}


def predict_optimal_sl_tp(symbol: str, price: float, direction: str, atr: float = None) -> Dict[str, float]:
    """
    חיזוי SL ו־TP חכם לפי כיוון, מחיר ו־ATR אם קיים.
    מעגל ל־tickSize החוקי של הסימבול.
    """
    try:
        direction = direction.upper()
        if direction not in ("LONG", "SHORT"):
            raise ValueError("כיוון לא חוקי (רק LONG או SHORT)")

        if atr and atr > 0:
            sl = price - atr if direction == "LONG" else price + atr
            tp = price + atr * 1.5 if direction == "LONG" else price - atr * 1.5
        else:
            sl = price * (0.99 if direction == "LONG" else 1.01)
            tp = price * (1.018 if direction == "LONG" else 0.982)

        min_gap = price * 0.005
        if abs(tp - sl) < min_gap:
            adjust = price * 0.01
            sl = price - adjust if direction == "LONG" else price + adjust
            tp = price + adjust * 1.6 if direction == "LONG" else price - adjust * 1.6

        if direction == "LONG" and not (sl < price < tp):
            sl, tp = price * 0.985, price * 1.025
        if direction == "SHORT" and not (tp < price < sl):
            sl, tp = price * 1.015, price * 0.975

        tick = get_precision_info(symbol).get("tickSize", 0.01)
        sl = round_tick(sl, tick)
        tp = round_tick(tp, tick)

        return {
            "sl": sl,
            "tp": tp
        }

    except Exception as e:
        return {"error": f"שגיאה בחיזוי SL/TP: {type(e).__name__} – {e}"}










