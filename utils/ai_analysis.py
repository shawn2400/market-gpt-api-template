# קובץ: utils/ai_analysis.py

import os
import openai
from utils.binance_client import client  # או כל client אחר שלך

# וידוא שיש לך משתנה סביבה OPENAI_API_KEY
openai.api_key = os.getenv("OPENAI_API_KEY")

def analyze_with_ai(
    symbol: str,
    rsi: float,
    adx: float,
    trend: str,
    pattern: str,
    volume: float
) -> dict:
    """
    מבצע קריאה ל-OpenAI כדי לקבל ניתוח AI על סמך פרמטרים טכניים.
    מחזיר dict עם התוצאה (למשל {'signal': 'BUY', 'confidence': 0.87}).
    """
    # כאן תבנה prompt מתאים
    prompt = (
        f"Analyze the following market data for {symbol}:\n"
        f"- RSI: {rsi}\n"
        f"- ADX: {adx}\n"
        f"- Trend: {trend}\n"
        f"- Pattern: {pattern}\n"
        f"- Volume: {volume}\n\n"
        "Please provide a trading recommendation (BUY/SELL/HOLD) and a confidence score."
    )

    resp = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "You are an expert crypto trading assistant."},
            {"role": "user",   "content": prompt}
        ],
        temperature=0.0,
        max_tokens=150
    )

    content = resp.choices[0].message.content
    # כאן תוסיף לוגיקה לפירוק התשובה למבנה dict
    # לדוגמה (פירוק very בסיסי - תתאים לפי הפורמט שתקבל):
    parts = [line.strip() for line in content.splitlines() if line.strip()]
    result = {}
    for p in parts:
        if p.upper().startswith("BUY") or p.upper().startswith("SELL") or p.upper().startswith("HOLD"):
            result["signal"] = p
        if "confidence" in p.lower():
            try:
                # מצא מספר עשרוני בתוך הטקסט
                import re
                match = re.search(r"(\d+(\.\d+)?)", p)
                if match:
                    result["confidence"] = float(match.group(1))
            except:
                pass

    return result
