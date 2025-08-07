# utils/ai_analysis.py

import os
import openai
import logging
import re
from dotenv import load_dotenv

load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")

async def analyze_with_ai(tf_results: list) -> dict:
    """
    מקבל רשימת תוצאות TF עבור סימבול ומחזיר ניתוח GPT.
    """
    if not openai.api_key:
        logging.error("[AI] ❌ מפתח OpenAI לא מוגדר.")
        return {"error": "OpenAI API key not configured"}

    try:
        symbol = tf_results[0]["symbol"]
        direction = tf_results[0]["direction"]
        avg_rsi = sum(x.get("rsi", 50) for x in tf_results) / len(tf_results)
        avg_adx = sum(x.get("adx", 20) for x in tf_results) / len(tf_results)
        avg_volume = sum(x.get("volume", 1000000) for x in tf_results) / len(tf_results)
        frames = [x["interval"] for x in tf_results]

        prompt = (
            f"You are a professional crypto analyst.\n"
            f"The following technical analysis was performed for {symbol} across timeframes: {', '.join(frames)}\n"
            f"- Direction: {direction}\n"
            f"- Avg RSI: {avg_rsi:.2f}\n"
            f"- Avg ADX: {avg_adx:.2f}\n"
            f"- Avg Volume: {avg_volume:,.0f}\n\n"
            f"1. Recommend: BUY / SELL / HOLD\n"
            f"2. Confidence (0–100%)\n"
            f"3. Keep format: Signal: BUY | Confidence: 85% | Reason: ...\n"
        )

        logging.info(f"[AI] 🔍 ניתוח GPT עבור {symbol} (frames={frames})")

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

        signal_match = re.search(r"Signal:\s*(BUY|SELL|HOLD)", content, re.IGNORECASE)
        confidence_match = re.search(r"Confidence:\s*(\d+(\.\d+)?)", content)

        if signal_match:
            result["signal"] = signal_match.group(1).upper()
        if confidence_match:
            result["confidence"] = float(confidence_match.group(1))

        result["symbol"] = symbol
        result["direction"] = direction
        result["quality_score"] = round(sum(x["quality_score"] for x in tf_results) / len(tf_results), 2)
        result["frames"] = frames
        result["details"] = tf_results

        logging.info(f"[AI] 🧠 פלט: {result}")
        return result

    except Exception as e:
        logging.error(f"[AI] ❌ שגיאת GPT: {e}")
        return {"error": str(e), "signal": "HOLD", "confidence": 0.0}













