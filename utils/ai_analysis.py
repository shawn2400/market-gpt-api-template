import os
import logging
import openai
from typing import Tuple, Optional

openai.api_key = os.getenv("OPENAI_API_KEY")
logger = logging.getLogger(__name__)

async def analyze_with_ai(symbol: str, rsi: float, adx: float, trend: str, pattern: str, volume: float) -> str:
    prompt = (
        f"Analyze the following crypto setup and decide whether it's a good LONG or SHORT opportunity.\n\n"
        f"Symbol: {symbol}\n"
        f"RSI: {rsi}\n"
        f"ADX: {adx}\n"
        f"Trend: {trend}\n"
        f"Pattern: {pattern}\n"
        f"Volume: {volume}\n\n"
        f"Return a short summary and a recommendation: LONG or SHORT."
    )
    try:
        response = await openai.ChatCompletion.acreate(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=150,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"AI analysis failed: {e}")
        return "AI analysis unavailable."

async def predict_optimal_sl_tp(symbol: str, direction: str, entry: float) -> Tuple[float, float]:
    prompt = (
        f"You are a crypto trading assistant. Given the symbol {symbol}, direction {direction}, "
        f"and entry price {entry}, calculate the optimal Stop Loss and Take Profit levels. "
        f"Use technical knowledge. Return ONLY two numbers: sl,tp"
    )
    try:
        response = await openai.ChatCompletion.acreate(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=30,
        )
        content = response.choices[0].message.content.strip()
        if "," in content:
            sl_str, tp_str = content.split(",", 1)
            return float(sl_str), float(tp_str)
        else:
            raise ValueError("Invalid format from AI.")
    except Exception as e:
        logger.warning(f"SL/TP AI fallback triggered: {e}")
        sl = round(entry * 0.985, 4) if direction == "LONG" else round(entry * 1.015, 4)
        tp = round(entry * 1.03, 4) if direction == "LONG" else round(entry * 0.97, 4)
        return sl, tp





































