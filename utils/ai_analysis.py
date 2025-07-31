import os
import openai
import logging

api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    logging.warning("⚠️ לא הוגדר OPENAI_API_KEY בסביבה")
else:
    openai.api_key = api_key

def analyze_with_ai(rsi, adx, trend, volume, pattern):
    if not openai.api_key:
        return {"answer": "API key not found", "score": 0}
    try:
        prompt = (
            f"ניתן ניתוח טכני: RSI={rsi}, ADX={adx}, מגמה={trend}, נפח={volume}, תבנית={pattern}. "
            "האם זה נראה כמו טרייד טוב? הסבר בקצרה ודרג בין 1 ל־10."
        )
        response = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )
        msg = response.choices[0].message.content
        score = next((int(s) for s in msg.split() if s.isdigit() and 1 <= int(s) <= 10), 0)
        return {"answer": msg, "score": score}
    except Exception as e:
        return {"answer": f"שגיאה: {str(e)}", "score": 0}

def predict_optimal_sl_tp(symbol, price, direction):
    if not openai.api_key:
        return {"sl": None, "tp": None}
    try:
        prompt = (
            f"הצג SL ו־TP מומלצים לסימבול {symbol} ב־{direction} סביב מחיר {price}. "
            "החזר בפורמט JSON: {{\"sl\": ..., \"tp\": ...}}"
        )
        response = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        content = response.choices[0].message.content
        out = eval(content.strip())
        return out if isinstance(out, dict) else {"sl": None, "tp": None}
    except Exception as e:
        return {"sl": None, "tp": None}











