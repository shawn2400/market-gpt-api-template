import os
import openai
import logging
from dotenv import load_dotenv

load_dotenv()

openai.api_key = os.getenv("OPENAI_API_KEY")
logger = logging.getLogger(__name__)

# 🧠 ניתוח GPT של סימבול
async def analyze_with_ai(indicators: dict) -> dict:
    try:
        prompt = (
            "Based on the following technical indicators, provide a trading recommendation "
            "(LONG/SHORT/NEUTRAL), with a confidence score (0-100), and a 1-line explanation.\n\n"
            f"RSI: {indicators.get('rsi')}\n"
            f"ADX: {indicators.get('adx')}\n"
            f"Trend: {indicators.get('trend')}\n"
            f"Pattern: {indicators.get('pattern')}\n"
            f"Volume: {indicators.get('volume')}\n\n"
            "Respond in this JSON format only:\n"
            '{"direction": "LONG", "confidence": 92, "note": "RSI rising, ADX strong"}'
        )

        response = await openai.ChatCompletion.acreate(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=100
        )

        content = response.choices[0].message.content
        return eval(content) if isinstance(content, str) else content

    except Exception as e:
        logger.error(f"[AI Analysis] GPT Error: {e}")
        return {"direction": "NEUTRAL", "confidence": 50, "note": "Fallback – AI unavailable"}

# 🤖 חיזוי SL/TP לפי נתוני טרייד
async def predict_optimal_sl_tp(symbol: str, direction: str, entry: float) -> tuple:
    try:
        prompt = (
            f"Suggest Stop Loss (SL) and Take Profit (TP) for a {direction} trade on {symbol}.\n"
            f"Entry Price: {entry}\n"
            f"Assume Binance Futures, high volatility. Use this format:\n"
            '{"sl": 123.45, "tp": 145.67}'
        )

        response = await openai.ChatCompletion.acreate(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.4,
            max_tokens=100
        )

        content = response.choices[0].message.content
        result = eval(content) if isinstance(content, str) else content
        return result.get("sl"), result.get("tp")

    except Exception as e:
        logger.warning(f"[SLTP AI] Failed to predict: {e}")
        # fallback: ±1.5% מהכניסה
        delta = entry * 0.015
        sl = round(entry - delta, 2) if direction == "LONG" else round(entry + delta, 2)
        tp = round(entry + 2 * delta, 2) if direction == "LONG" else round(entry - 2 * delta, 2)
        return sl, tp






































