import os
from dotenv import load_dotenv
import openai

# טעינת משתני סביבה
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


def predict_optimal_sl_tp(symbol: str, price: float, direction: str, atr: float = None) -> dict:
    """
    חיזוי SL/TP חכם – מבוסס כיוון + ATR אם קיים.
    :param symbol: סימול
    :param price: מחיר נוכחי
    :param direction: 'LONG' או 'SHORT'
    :param atr: ממוצע טווח תנודתיות (אופציונלי)
    :return: dict עם stop loss ו־take profit
    """
    try:
        direction = direction.upper()
        if direction not in {"LONG", "SHORT"}:
            raise ValueError("כיוון לא חוקי: נדרש 'LONG' או 'SHORT'")

        # ברירת מחדל אם אין ATR
        if not atr or atr <= 0:
            sl_pct = 0.01  # 1%
            tp_pct = 0.015  # 1.5%
            sl = price * (1 - sl_pct) if direction == "LONG" else price * (1 + sl_pct)
            tp = price * (1 + tp_pct) if direction == "LONG" else price * (1 - tp_pct)
        else:
            sl = price - atr if direction == "LONG" else price + atr
            tp = price + 1.5 * atr if direction == "LONG" else price - 1.5 * atr

        # עיגול ל־4 ספרות
        sl = round(sl, 4)
        tp = round(tp, 4)

        # הגנה: אם המרווח קטן מדי (פחות מ־0.5%)
        if abs(tp - sl) / price < 0.005:
            adjust = price * 0.01  # תיקון של 1%
            sl = round(price - adjust, 4) if direction == "LONG" else round(price + adjust, 4)
            tp = round(price + adjust * 1.5, 4) if direction == "LONG" else round(price - adjust * 1.5, 4)

        return {"sl": sl, "tp": tp}
    except Exception as e:
        return {"error": f"שגיאה בחיזוי SL/TP: {e}"}




