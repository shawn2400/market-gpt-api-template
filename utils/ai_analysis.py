# utils/ai_analysis.py
import logging
import re
import traceback
from typing import Tuple, List, Dict, Any

from utils import config
from utils.ai_client import chat
from utils.sl_tp_utils import calculate_sl_tp

def _avg(vals, default: float = 0.0) -> float:
    xs = [float(v) for v in vals if isinstance(v, (int, float))]
    return round(sum(xs) / len(xs), 4) if xs else float(default)

def _parse_signal_conf(text: str) -> Dict[str, Any]:
    out = {"signal": "HOLD", "confidence": 0.0}
    try:
        m_sig = re.search(r"Signal:\s*(BUY|SELL|HOLD)", text, re.IGNORECASE)
        if m_sig:
            out["signal"] = m_sig.group(1).upper()
        m_conf = re.search(r"Confidence:\s*(\d+(\.\d+)?)", text)
        if m_conf:
            out["confidence"] = float(m_conf.group(1))
    except Exception:
        pass
    return out

async def analyze_with_ai(tf_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    קולט את פלט ה-multi_tf_scan (לסמל יחיד, מסגרות זמן שונות),
    ומחזיר החלטת AI יציבה ומפורמטת.
    """
    try:
        if not tf_results or not isinstance(tf_results, list):
            return {"error": "empty tf_results", "signal": "HOLD", "confidence": 0.0}

        symbol = tf_results[0].get("symbol", "UNKNOWN")
        direction = tf_results[0].get("direction", "LONG")
        frames = [x.get("interval", "?") for x in tf_results]

        avg_rsi = _avg([x.get("rsi") for x in tf_results], default=50.0)
        avg_adx = _avg([x.get("adx") for x in tf_results], default=20.0)
        avg_volume = _avg([x.get("volume") for x in tf_results], default=1_000_000.0)
        q_scores = [float(x.get("quality_score", 0.0)) for x in tf_results]
        avg_q = round(sum(q_scores) / len(q_scores), 2) if q_scores else 0.0

        prompt = (
            f"You are a professional crypto analyst.\n"
            f"Technical analysis for {symbol} across frames: {', '.join(frames)}\n"
            f"- Direction: {direction}\n"
            f"- Avg RSI: {avg_rsi:.2f}\n"
            f"- Avg ADX: {avg_adx:.2f}\n"
            f"- Avg Volume: {avg_volume:,.0f}\n"
            f"- Avg Quality: {avg_q:.2f}\n\n"
            f"Return exactly this format on a single line:\n"
            f"Signal: BUY/SELL/HOLD | Confidence: <0-100>% | Reason: <short reason>\n"
        )

        logging.info(f"[AI] analyze_with_ai prompt for {symbol} (frames={frames})")
        content = await chat(
            prompt,
            system="Be concise and deterministic. No markdown.",
            model=getattr(config, "OPENAI_MODEL", "gpt-4o-mini"),
            temperature=0.0,
            max_tokens=200,
            retries=2,
        )

        parsed = _parse_signal_conf(content)
        result = {
            "symbol": symbol,
            "direction": direction,
            "quality_score": avg_q,
            "frames": frames,
            "signal": parsed["signal"],
            "confidence": parsed["confidence"],
            "raw": content,
            "details": tf_results,
        }
        return result

    except Exception as e:
        logging.error(f"[AI] analyze_with_ai exception: {e}\n{traceback.format_exc()}")
        return {"error": str(e), "signal": "HOLD", "confidence": 0.0}

async def predict_optimal_sl_tp(symbol: str, direction: str, entry_price: float, atr: float = None) -> Tuple[float, float]:
    """
    חישוב SL/TP בעזרת GPT (עם פולבק דטרמיניסטי ל-calculate_sl_tp).
    """
    try:
        prompt = (
            f"You are a crypto trading assistant.\n"
            f"Symbol: {symbol}\n"
            f"Trend: {direction.upper()}\n"
            f"Entry Price: {entry_price}\n"
            f"ATR: {atr if atr is not None else 'N/A'}\n\n"
            f"Suggest optimized SL and TP levels based on trend and entry. "
            f"Return exactly: SL: <number>, TP: <number>"
        )

        logging.info(f"[AI] SL/TP analysis for {symbol}")
        content = await chat(
            prompt,
            system="Reply with 'SL: <num>, TP: <num>' only.",
            model=getattr(config, "OPENAI_MODEL", "gpt-4o-mini"),
            temperature=0.2,
            max_tokens=40,
            retries=2,
        )

        m = re.search(r"SL:\s*([0-9]*\.?[0-9]+)\s*,\s*TP:\s*([0-9]*\.?[0-9]+)", content)
        if m:
            sl, tp = float(m.group(1)), float(m.group(2))
            return round(sl, 6), round(tp, 6)

        logging.warning(f"[AI] SL/TP parse failed, content={content!r}; using fallback")

    except Exception as e:
        logging.warning(f"[AI-SLTP] Exception: {e}; using fallback")

    # Fallback דטרמיניסטי
    return calculate_sl_tp(entry_price=entry_price, direction=direction, atr=atr)

























