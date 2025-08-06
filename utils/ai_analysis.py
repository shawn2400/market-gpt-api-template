# utils/ai_analysis.py

import os
import openai
import logging
import re
from dotenv import load_dotenv

load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")

async def analyze_with_ai(
    symbol: str,
    rsi: float,
    adx: float,
    trend: str,
    pattern: str,
    volume: float
) -> dict:
    if not openai.api_key:
        logging.error("[AI] ❌ מפתח OpenAI לא מוגדר.")
        return {"error": "OpenAI API key not configured"}

    logging.info(f"[AI] 🔍 ניתוח GPT עבור {symbol}")

    prompt = (
        f"You are an expert crypto trading assistant.\n"
        f"Analyze the following market conditions for the symbol {symbol}:\n"
        f"- RSI: {rsi:.2f}\n"
        f"- ADX: {adx:.2f}\n"
        f"- Volume: {volume:,.0f}\n"
        f"- Trend Direction: {trend.upper()}\n"
        f"- Candlestick Pattern: {pattern}\n\n"
        f"Based on this data:\n"
        f"1. Recommend a clear trading action (BUY, SELL or HOLD).\n"
        f"2. Estimate your confidence level in percentage (0–100%).\n"
        f"3. Write in a single concise paragraph.\n"
        f"4. Use this format exactly: Signal: BUY | Confidence: 75% | Reason: ...\n"
    )

    try:
        resp = await openai.ChatCompletion.acreate(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=200
        )

        if not resp.choices:
            return {"signal": "HOLD", "confidence": 0.0, "reason": "No response from AI"}

        content = resp.choices[0].message.content.strip()
        result = {"signal": "HOLD", "confidence": 0.0, "raw": content}

        # פורמט צפוי: Signal: BUY | Confidence: 72% | Reason: ...
        signal_match = re.search(r"Signal:\s*(BUY|SELL|HOLD)", content, re.IGNORECASE)
        confidence_match = re.search(r"Confidence:\s*(\d+(\.\d+)?)", content)

        if signal_match:
            result["signal"] = signal_match.group(1).upper()
        if confidence_match:
            result["confidence"] = float(confidence_match.group(1))

        logging.info(f"[AI] 🧠 פלט: {result}")
        return result

    except Exception as e:
        logging.error(f"[AI] ❌ שגיאת GPT: {e}")
        return {"error": str(e), "signal": "HOLD", "confidence": 0.0}











