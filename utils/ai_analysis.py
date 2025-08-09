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
    if not openai.api_key or openai.api_key.strip() == "":
        logging.error("[AI] OpenAI API key not configured")
        return {"error": "OpenAI API key not configured"}

    try:
        symbol = tf_results[0]["symbol"]
        direction = tf_results[0]["direction"]
        avg_rsi = sum(x.get("rsi", 50) for x in tf_results) / len(tf_results)
        avg_adx = sum(x.get("adx", 20) for x in tf_results) / len(tf_results)
        avg_volume = sum(x.get("volume", 1_000_000) for x in tf_results) / len(tf_results)
        frames = [x["interval"] for x in tf_results]

        prompt = (
            f"You are a professional crypto analyst.\n"
            f"Technical analysis for {symbol} across {', '.join(frames)}\n"
            f"- Direction: {direction}\n"
            f"- Avg RSI: {avg_rsi:.2f}\n"
            f"- Avg ADX: {avg_adx:.2f}\n"
            f"- Avg Volume: {avg_volume:,.0f}\n\n"
            f"1. Recommend: BUY / SELL / HOLD\n"
            f"2. Confidence (0-100%)\n"
            f"3. Format: Signal: BUY | Confidence: 85% | Reason: ...\n"
        )
        logging.info(f"[AI] Sending prompt for {symbol}")

        response = await openai.chat.completions.acreate(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=200
        )

        content = response.choices[0].message.content.strip()
        logging.debug(f"[AI] Response: {content}")

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

        logging.info(f"[AI] Result: {result}")
        return result

    except Exception as e:
        logging.error(f"[AI] Exception: {e}\n{traceback.format_exc()}")
        return {"error": str(e), "signal": "HOLD", "confidence": 0.0}


async def predict_optimal_sl_tp(symbol: str, direction: str, entry_price: float, atr: float = None) -> Tuple[float, float]:
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
        logging.info(f"[AI] SL/TP analysis for {symbol}")

        response = await openai.chat.completions.acreate(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=100
        )
        content = response.choices[0].message.content.strip()
        logging.debug(f"[AI] SL/TP response: {content}")

        import re
        match = re.search(r"SL:\s*([\d.]+)[,\s]+TP:\s*([\d.]+)", content)
        if match:
            sl, tp = float(match.group(1)), float(match.group(2))
            return round(sl, 6), round(tp, 6)

    except Exception as e:
        logging.warning(f"[AI-SLTP] Fallback: {e}")

    from utils.sl_tp_utils import calculate_sl_tp
    return calculate_sl_tp(entry_price=entry_price, direction=direction, atr=atr)





















