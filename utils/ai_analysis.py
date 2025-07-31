# utils/ai_analysis.py

import os
import logging
import re
import openai

# טען את המפתח מהסביבה
openai.api_key = os.getenv("OPENAI_API_KEY")

def analyze_with_ai(rsi, adx, trend, volume, pattern):
    prompt = f"""
אתה מערכת מסחר חכמה. נתח את השוק לפי הנתונים:
- RSI: {rsi}
- ADX: {adx}
- מגמה: {trend}
- נפח: {volume}
- תבנית: {pattern}

האם כדאי להיכנס לטרייד? ענה בקצרה מאוד בעברית, והחזר גם ציון איכות בין 0 ל־10.
"""

    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "אתה אנליסט שוק מתמחה בקריפטו. תשיב תשובה קצרה וברורה."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.5
        )
        answer = response.choices[0].message.content.strip()
        score = extract_score_from_text(answer)
        return {"answer": answer, "score": score}

    except Exception as e:
        logging.error(f"[AI Error] analyze_with_ai: {e}")
        return {"answer": "❌ תקלה בניתוח GPT", "score": 0}


def predict_optimal_sl_tp(direction: str, entry: float):
    """
    חיזוי SL/TP בסיסי לפי כיוון וכניסה.
    """
    try:
        direction = direction.upper()
        if direction not in ["LONG", "SHORT"]:
            raise ValueError("כיוון לא חוקי")

        sl = round(entry * 0.975, 4) if direction == "LONG" else round(entry * 1.025, 4)
        tp = round(entry * 1.05, 4) if direction == "LONG" else round(entry * 0.95, 4)
        return {"sl": sl, "tp": tp}

    except Exception as e:
        logging.error(f"[SL/TP Prediction Error] {e}")
        return {"sl": None, "tp": None}


def extract_score_from_text(text: str) -> int:
    """
    חילוץ מספר בין 0 ל־10 מתוך תשובת GPT.
    """
    try:
        matches = re.findall(r"\b([0-9]{1,2})(?:\/10)?\b", text)
        for m in matches:
            val = int(m)
            if 0 <= val <= 10:
                return val
    except Exception as e:
        logging.warning(f"[extract_score_from_text] שגיאה בפירוש טקסט: {e}")
    return 0



















