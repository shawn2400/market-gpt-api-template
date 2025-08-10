# utils/ai_analysis.py
import logging
import re
import traceback
from typing import Tuple, Optional, List, Dict

from utils.sl_tp_utils import calculate_sl_tp
from utils import config

# OpenAI v1.x (Async)
try:
    from openai import AsyncOpenAI
except Exception as e:
    AsyncOpenAI = None
    logging.warning(f"[AI] OpenAI SDK import failed: {e}")

_client = None
if AsyncOpenAI and config.OPENAI_API_KEY:
    try:
        _client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
    except Exception as e:
        logging.error(f"[AI] failed to init AsyncOpenAI: {e}")
        _client = None

MODEL = config.OPENAI_MODEL or "gpt-4o-mini"

def _avg(values: List[float], default: float = 0.0) -> float:
    try:
        vals = [float(x) for x in values if x is not None]
        return sum(vals) / len(vals) if vals else float(default)
    except Exception:
        return float(default)

async def analyze_with_ai(tf_results: List[Dict]) -> dict:
    """
    מקבל רשימת תוצאות TF מסורק (dict לכל TF) ומחזיר:
    {
      symbol, direction, quality_score, frames, signal (BUY/SELL/HOLD),
      confidence (0-100), details: [...]
    }
    אם אין API KEY/SDK → יוחזר {"error": "..."} ונמשיך בלי לעצור את הזרימה.
    """
    if not _client:
        logging.error("[AI] OpenAI API key not configured or SDK missing")
        return {"error": "OpenAI API key not configured"}

    try:
        if not tf_results or not isinstance(tf_results, list):
            return {"error": "tf_results invalid"}

        symbol = str(tf_results[0].get("symbol", "")).upper()
        direction = str(tf_results[0].get("direction", "LONG")).upper()
        avg_rsi = _avg([x.get("rsi", 50) for x in tf_results], 50.0)
        avg_adx = _avg([x.get("adx", 20) for x in tf_results], 20.0)
        avg_volume = _avg([x.get("volume", 1_000_000) for x in tf_results], 1_000_000.0)
        frames = [str(x.get("interval", "NA")) for x in tf_results]
        q_score = round(_avg([x.get("quality_score", 0) for x in tf_results], 0.0), 2)

        prompt = (
            "You are a professional crypto analyst.\n"
            f"Technical analysis for {symbol} across {', '.join(frames)}\n"
            f"- Direction: {direction}\n"
            f"- Avg RSI: {avg_rsi:.2f}\n"
            f"- Avg ADX: {avg_adx:.2f}\n"
            f"- Avg Volume: {avg_volume:,.0f}\n\n"
            "1. Recommend: BUY / SELL / HOLD\n"
            "2. Confidence (0-100%)\n"
            "3. Format exactly: Signal: BUY | Confidence: 85% | Reason: ...\n"
        )
        logging.info(f"[AI] Sending prompt for {symbol} ({MODEL})")

        resp = await _client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=200,
        )

        content = (resp.choices[0].message.content or "").strip()
        logging.debug(f"[AI] Response: {content}")

        result = {"signal": "HOLD", "confidence": 0.0, "raw": content}
        m_signal = re.search(r"Signal:\s*(BUY|SELL|HOLD)", content, re.IGNORECASE)
        m_conf = re.search(r"Confidence:\s*(\d+(\.\d+)?)", content)

        if m_signal:
            result["signal"] = m_signal.group(1).upper()
        if m_conf:
            result["confidence"] = float(m_conf.group(1))

        result.update({
            "symbol": symbol,
            "direction": direction,
            "quality_score": q_score,
            "frames": frames,
            "details": tf_results,
        })
        logging.info(f"[AI] Result: {result}")
        return result

    except Exception as e:
        logging.error(f"[AI] Exception: {e}\n{traceback.format_exc()}")
        return {"error": str(e), "signal": "HOLD", "confidence": 0.0}

async def predict_optimal_sl_tp(symbol: str, direction: str, entry_price: float, atr: Optional[float] = None) -> Tuple[float, float]:
    """
    מנסה לקבל SL/TP אופטימליים מהמודל. אם נכשל/אין SDK/KEY → פולבק דטרמיניסטי.
    """
    # אם אין לקוח – פולבק
    if not _client:
        return calculate_sl_tp(entry_price=entry_price, direction=direction, atr=atr)

    try:
        prompt = (
            "You are a crypto trading assistant.\n"
            f"Symbol: {symbol}\n"
            f"Trend: {direction.upper()}\n"
            f"Entry Price: {entry_price}\n"
            f"ATR: {atr if atr is not None else 'N/A'}\n\n"
            "Suggest optimized SL and TP levels based on current trend and price.\n"
            "Return strictly in format: SL: <value>, TP: <value>\n"
        )
        logging.info(f"[AI] SL/TP analysis for {symbol} ({MODEL})")

        resp = await _client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=120,
        )
        content = (resp.choices[0].message.content or "").strip()
        logging.debug(f"[AI] SL/TP response: {content}")

        m = re.search(r"SL:\s*([\d.]+)[,\s]+TP:\s*([\d.]+)", content)
        if m:
            sl = float(m.group(1))
            tp = float(m.group(2))
            return (round(sl, 6), round(tp, 6))

    except Exception as e:
        logging.warning(f"[AI-SLTP] Fallback due to: {e}")

    # פולבק דטרמיניסטי
    return calculate_sl_tp(entry_price=entry_price, direction=direction, atr=atr)

























