import os
import openai
import logging
import re
import traceback
from typing import Tuple
from dotenv import load_dotenv

load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")

async def analyze_with_ai(tf_results: list) -> dict:
    """
    ניתוח GPT עבור תוצאות טכניות לפי מספר טיימפריימים.
    """
    if not openai.api_key or openai.api_key.strip() == "":
        logging.error("[AI] ❌ מפתח OpenAI לא מוגדר או ריק.")
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
        logging.debug(f"[AI] ▶️ שליחת בקשה ל־OpenAI GPT עם prompt:\n{prompt}")

        resp = await openai.ChatCompletion.acreate(
            model="gpt-5",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=200
        )

        if not resp.choices:
            logging.warning("[AI] ⚠️ תגובת GPT ריקה, מחזירים HOLD כברירת מחדל")
            return {"signal": "HOLD", "confidence": 0.0, "reason": "No response from AI"}

        content = resp.choices[0].message.content.strip()
        logging.debug(f"[AI] 📩 תגובת GPT מלאה:\n{content}")

        result = {"signal": "HOLD", "confidence": 0.0, "raw": content}

        signal_match = re.search(r"Signal:\s*(BUY|SELL|HOLD)", content, re.IGNORECASE)
        confidence_match = re.search(r"Confidence:\s*(\d+(\.\d+)?)(%)?", content)

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
        logging.error(f"[AI] ❌ שגיאת GPT: {e}\n{traceback.format_exc()}")
        return {"error": str(e), "signal": "HOLD", "confidence": 0.0}

async def predict_optimal_sl_tp(symbol: str, direction: str, entry_price: float, atr: float = None) -> Tuple[float, float]:
    """
    ניתוח GPT לחישוב SL ו־TP חכמים בהתבסס על מגמה, ATR ו־entry.
    אם ה-GPT נכשל — fallback לחישוב קלאסי.
    """
    try:
        prompt = (
            f"You are a crypto trading assistant.\n"
            f"Symbol: {symbol}\n"
            f"Trend: {direction.upper()}\n"
            f"Entry Price: {entry_price}\n"
            f"ATR: {atr or 'N/A'}\n\n"
            f"Suggest optimized SL and TP levels based on current trend and price.\n"
            f"Return in format: SL: <value>, TP: <value>"
        )

        logging.info(f"[AI] 🔁 ניתוח GPT עבור SL/TP של {symbol}...")
        logging.debug(f"[AI] ▶️ שליחת בקשה ל־OpenAI GPT עם prompt:\n{prompt}")

        response = await openai.ChatCompletion.acreate(
            model="gpt-5",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=100
        )

        content = response.choices[0].message.content.strip()
        logging.debug(f"[AI] 📩 תגובת GPT מלאה ל-SL/TP:\n{content}")

        match = re.search(r"SL:\s*([\d.]+)[,\s]+TP:\s*([\d.]+)", content)
        if match:
            sl, tp = float(match.group(1)), float(match.group(2))
            return round(sl, 6), round(tp, 6)

    except Exception as e:
        logging.warning(f"[AI-SLTP] ⚠️ Fallback to classic SL/TP: {e}\n{traceback.format_exc()}")

    # fallback לחישוב רגיל
    from utils.sl_tp_utils import calculate_sl_tp
    return calculate_sl_tp(entry_price=entry_price, direction=direction, atr=atr)
















