# ai_analysis.py

import os
from dotenv import load_dotenv
import openai

load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")

def analyze_with_ai(data: dict) -> dict:
    """
    ניתוח שוק חכם בעזרת GPT (OpenAI API).
    """
    if not data or not isinstance(data, dict):
        return {"error": "Invalid or empty input data"}

    prompt = f"""
    הנתונים הטכניים שקיבלתי הם:
    RSI: {data.get("rsi")}
    ADX: {data.get("adx")}
    מגמה: {data.get("trend")}
    נפח מסחר: {data.get("volume")}
    תבנית: {data.get("pattern")}

    האם כדאי להיכנס לעסקה? נא נתח בקצרה.
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

