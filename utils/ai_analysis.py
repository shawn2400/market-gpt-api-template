import os
import openai
from dotenv import load_dotenv

load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")

def analyze_with_gpt(data):
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
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"שגיאה בניתוח GPT: {e}"
