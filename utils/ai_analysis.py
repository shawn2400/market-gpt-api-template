import os
import openai
import logging

openai.api_key = os.getenv("OPENAI_API_KEY")
logger = logging.getLogger(__name__)

# הסבר וניתוח GPT
async def analyze_with_ai(data: dict) -> str:
    prompt = f"""
ספק ניתוח קצר על המטבע {data['symbol']}:
• RSI: {data['rsi']}
• ADX: {data['adx']}
• מגמה: {data['trend']}
• תבנית: {data['pattern']}
• נפח: {data['volume']}
• תן ניתוח קצר והמלצה (LONG/SHORT)
"""
    try:
        response = await openai.ChatCompletion.acreate(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "אתה אנליסט שוק קריפטו מקצועי."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.4,
            max_tokens=300
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"AI analysis failed: {e}")
        return "❌ ניתוח GPT נכשל"

# חיזוי SL/TP חכם
async def predict_optimal_sl_tp(symbol: str, direction: str, entry: float) -> tuple:
    prompt = f"""
ספק SL ו־TP לטרייד:
• סימבול: {symbol}
• כיוון: {direction}
• מחיר כניסה: {entry}

תן תשובה בפורמט: SL=..., TP=...
"""
    try:
        response = await openai.ChatCompletion.acreate(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "אתה מחשב SL/TP עבור טריידים בזמן אמת."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=60
        )
        content = response.choices[0].message.content.strip()
        sl = float(content.split("SL=")[1].split(",")[0])
        tp = float(content.split("TP=")[1].split()[0])
        return sl, tp
    except Exception as e:
        logger.warning(f"Fallback SLTP (AI failed): {e}")
        fallback_sl = round(entry * (0.985 if direction == "LONG" else 1.015), 2)
        fallback_tp = round(entry * (1.035 if direction == "LONG" else 0.965), 2)
        return fallback_sl, fallback_tp






































