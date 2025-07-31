# utils/ai_analysis.py

import os
import logging
import re
from openai import AsyncOpenAI

client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

async def analyze_with_ai(rsi, adx, trend, volume, pattern):
    prompt = f"""
אתה מערכת מסחר חכמה. נתח את השוק לפי הנתונים:
- RSI: {rsi}
- ADX: {adx}
- מגמה: {trend}
- נפח: {volume}
- תבנית: {pattern}

האם כדאי להיכנס לטרייד? ענה בקצרה מאוד והחזר גם ציון מ-0 עד 10.
"""
    try:
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "אתה אנליסט שוק מתמחה בקריפטו."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.5
        )
        answer = response.choices[0].message.content
        score = extract_score_from_text(answer)
        return {"answer": answer, "score": score}
    except Exception as e:
        logging.error(f"[AI Error] {e}")
        return {"answer": "❌ תקלה בניתוח GPT", "score": 0}

async def predict_optimal_sl_tp(direction: str, entry: float):
    try:
        sl = round(entry * 0.975, 4) if direction.upper() == "LONG" else round(entry * 1.025, 4)
        tp = round(entry * 1.05, 4) if direction.upper() == "LONG" else round(entry * 0.95, 4)
        return {"sl": sl, "tp": tp}
    except Exception as e:
        logging.error(f"[SL/TP Prediction Error] {e}")
        return {"sl": None, "tp": None}

def extract_score_from_text(text):
    matches = re.findall(r"\b([0-9]{1,2})(?:\/10)?\b", text)
    if matches:
        score = int(matches[0])
        return min(score, 10)
    return 0















