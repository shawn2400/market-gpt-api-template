# utils/ai_analysis.py
import logging
import re
import traceback
from typing import Tuple, List, Dict

import openai
from utils import config
from utils.sl_tp_utils import calculate_sl_tp

# קונפיג OpenAI
openai.api_key = config.OPENAI_API_KEY
MODEL = config.OPENAI_MODEL

def _norm_direction(d: str) -> str:
    d = (d or "").strip().upper()
    if d in ("LONG", "BUY"): return "LONG"
    if d in ("SHORT", "SELL"): return "SHORT"
    return "LONG"

async def analyze_with_ai(tf_results: List[Dict]) -> Dict:
    """
    קלט: רשימת תוצאות TF עבור סימבול אחד.
    פלט: dict אחיד {symbol, direction, quality_score, signal, confidence, frames, details, raw?} או {"error": ...}
    """
    try:
        if not tf_results:
            return {"error": "empty tf_results"}

        symbol = str(tf_results[0].get("symbol", "")).upper()
        direction = _norm_direction(tf_results[0].get("direction"))
        frames = [str(x.get("interval", "?")) for x in tf_results]
        avg_rsi = sum(float(x.get("rsi", 50) or 50) for x in tf_results) / len(tf_results)
        avg_adx = sum(float(x.get("adx", 20) or 20) for x in tf_results) / len(tf_results)
        avg_volume = sum(float(x.get("volume", 1_000_000) or 1_000_000) for x in tf_results) / len(tf_results)
        avg_quality = sum(float(x.get("quality_score", 0) or 0) for x in tf_results) / len(tf_results)

        # אם אין מפתח – נחזיר fallback מאוחד (ללא כישלון קשיח)
        if not (openai.api_key and openai.api_key.strip()):
            return {
                "symbol": symbol,
                "direction": direction,
                "quality_score": round(avg_quality, 2),
                "signal": "BUY" if direction == "LONG" else "SELL",
                "confidence": 50.0,
                "frames": frames,
                "details": tf_results,
                "error": "OpenAI API key not configured"
            }

        prompt = (
            f"You are a professional crypto analyst.\n"
            f"Technical analysis for {symbol} across {', '.join(frames)}\n"
            f"- Direction: {direction}\n"
            f"- Avg RSI: {avg_rsi:.2f}\n"
            f"- Avg ADX: {avg_adx:.2f}\n"
            f"- Avg Volume: {avg_volume:,.0f}\n\n"
            f"1. Recommend: BUY / SELL / HOLD\n"
            f"2. Confidence (0-100%)\n"
            f"3. Format exactly: Signal: BUY | Confidence: 85% | Reason: ...\n"
        )
        logging.info(f"[AI] Sending prompt for {symbol}")

        resp = await openai.chat.completions.acreate(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=220
        )
        content = resp.choices[0].message.content.strip()
        logging.debug(f"[AI] Response: {content}")

        signal = "HOLD"
        conf = 0.0
        m1 = re.search(r"Signal:\s*(BUY|SELL|HOLD)", content, re.IGNORECASE)
        m2 = re.search(r"Confidence:\s*(\d+(?:\.\d+)?)", content)
        if m1: signal = m1.group(1).upper()
        if m2: conf = float(m2.group(1))

        return {
            "symbol": symbol,
            "direction": direction,
            "quality_score": round(avg_quality, 2),
            "signal": signal if signal in ("BUY", "SELL", "HOLD") else "HOLD",
            "confidence": max(0.0, min(100.0, conf)),
            "frames": frames,
            "details": tf_results,
            "raw": content
        }

    except Exception as e:
        logging.error(f"[AI] Exception: {e}\n{traceback.format_exc()}")
        symbol = str(tf_results[0].get("symbol", "")).upper() if tf_results else "UNKNOWN"
        direction = _norm_direction(tf_results[0].get("direction")) if tf_results else "LONG"
        avg_quality = (
            sum(float(x.get("quality_score", 0) or 0) for x in tf_results) / max(1, len(tf_results))
            if tf_results else 0.0
        )
        return {
            "error": str(e),
            "symbol": symbol,
            "direction": direction,
            "quality_score": round(avg_quality, 2),
            "signal": "HOLD",
            "confidence": 0.0,
            "frames": [str(x.get("interval", "?")) for x in tf_results] if tf_results else [],
            "details": tf_results or []
        }

async def predict_optimal_sl_tp(symbol: str, direction: str, entry_price: float, atr: float = None) -> Tuple[float, float]:
    """
    תמיד מחזיר (stop, tp) כ-tuple; אם ה-AI נכשל—נופל ל-calculate_sl_tp.
    מאמת: LONG => stop < entry < tp, SHORT => tp < entry < stop.
    """
    direction = _norm_direction(direction)
    try:
        if openai.api_key and openai.api_key.strip():
            prompt = (
                f"You are a crypto trading assistant.\n"
                f"Symbol: {symbol}\n"
                f"Trend: {direction}\n"
                f"Entry Price: {entry_price}\n"
                f"ATR: {atr or 'N/A'}\n\n"
                f"Suggest optimized SL and TP. Format: SL: <value>, TP: <value>"
            )
            logging.info(f"[AI] SL/TP analysis for {symbol}")

            resp = await openai.chat.completions.acreate(
                model=MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=120
            )
            content = resp.choices[0].message.content.strip()
            logging.debug(f"[AI] SL/TP response: {content}")

            m = re.search(r"SL:\s*([\d.]+)[,\s]+TP:\s*([\d.]+)", content)
            if m:
                sl, tp = float(m.group(1)), float(m.group(2))
                if (direction == "LONG" and sl < entry_price < tp) or (direction == "SHORT" and tp < entry_price < sl):
                    return round(sl, 6), round(tp, 6)
                else:
                    logging.warning(f"[AI-SLTP] Invalid levels for {direction}: entry={entry_price}, SL={sl}, TP={tp} -> fallback")
    except Exception as e:
        logging.warning(f"[AI-SLTP] Fallback due to error: {e}")

    sl, tp = calculate_sl_tp(entry_price=entry_price, direction=direction, atr=atr)
    return float(sl), float(tp)
























