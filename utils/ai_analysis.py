# utils/ai_analysis.py

import os
from dotenv import load_dotenv
import openai
from typing import Dict, Union

load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")

def analyze_with_ai(data: Dict[str, Union[str, float]]) -> Dict[str, Union[str, float]]:
    """
    ניתוח GPT על סמך RSI, ADX, מגמה, תבנית ונפח.
    מחזיר טקסט המלצה עם סיכום ניתוח.
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
    הסבר את המסקנה בקצרה.
    """

    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "אתה אנליסט טכני של שוק הקריפטו. תן תשובה תמציתית, מקצועית ולעניין בלבד – בלי ניחושים."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.4,
            max_tokens=300
        )
        content = response.choices[0].message.content.strip()
        return {
            "answer": content,
            "score": 0.9  # ניקוד סטטי, ניתן להרחיב בעתיד
        }

    except openai.error.OpenAIError as e:
        return {"error": f"שגיאת GPT: {str(e)}"}


def predict_optimal_sl_tp(symbol: str, price: float, direction: str, atr: float = None) -> Dict[str, float]:
    """
    חיזוי SL ו־TP חכם לפי כיוון, מחיר ו־ATR אם קיים.
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
            tp = price * (1.015 if direction == "LONG" else 0.985)

        # הבטחת מרווח מינימלי
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







