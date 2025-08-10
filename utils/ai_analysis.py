# utils/ai_analysis.py
import logging
import re
import traceback
from typing import Tuple, List, Dict, Any, Optional

from utils import config
from utils.ai_client import chat
from utils.sl_tp_utils import calculate_sl_tp


def _avg(vals, default: float = 0.0) -> float:
    xs = []
    for v in vals or []:
        try:
            xs.append(float(v))
        except Exception:
            pass
    return round(sum(xs) / len(xs), 4) if xs else float(default)


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(v)))


def _parse_signal_conf(text: str) -> Dict[str, Any]:
    """
    מצפה ל:
      Signal: BUY/SELL/HOLD | Confidence: <0-100> | Reason: <short>
    סובלני לפסיקים/רווחים/אחוזים.
    """
    out = {"signal": "HOLD", "confidence": 0.0, "reason": ""}

    if not isinstance(text, str) or not text.strip():
        return out

    try:
        # סיגנל
        m_sig = re.search(r"Signal\W*\:\W*(BUY|SELL|HOLD)", text, re.IGNORECASE)
        if m_sig:
            out["signal"] = m_sig.group(1).upper()
        # קונפ'
        m_conf = re.search(r"Confidence\W*\:\W*([0-9]+(?:\.[0-9]+)?)\s*%?", text, re.IGNORECASE)
        if m_conf:
            out["confidence"] = _clamp(float(m_conf.group(1)), 0.0, 100.0)
        # סיבה
        m_reason = re.search(r"Reason\W*\:\W*(.+)$", text, re.IGNORECASE)
        if m_reason:
            out["reason"] = m_reason.group(1).strip()
    except Exception:
        pass

    # הגנות:
    if out["signal"] not in ("BUY", "SELL", "HOLD"):
        out["signal"] = "HOLD"
    out["confidence"] = _clamp(out["confidence"], 0.0, 100.0)
    return out


def _get_metric(d: Dict[str, Any], key: str):
    if key in d:
        return d.get(key)
    inds = d.get("indicators") or {}
    return inds.get(key)


def _dedup_str(seq: List[str]) -> List[str]:
    seen = set()
    out = []
    for s in seq or []:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


async def _safe_chat(prompt: str, *, system: str, model: Optional[str], temperature: float, max_tokens: int, retries: int) -> str:
    """
    מעטפת בטוחה ל-chat: מחזירה מחרוזת ריקה במקרה שגיאה.
    """
    try:
        return await chat(
            prompt,
            system=system,
            model=model or getattr(config, "OPENAI_MODEL", "gpt-4o-mini"),
            temperature=temperature,
            max_tokens=max_tokens,
            retries=retries,
        )
    except Exception as e:
        logging.error(f"[AI] chat failed: {e}")
        return ""


async def analyze_with_ai(tf_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    קולט פלט multi_tf_scan (לסמל יחיד, מסגרות זמן שונות) ומחזיר החלטה מרוכזת.
    """
    try:
        if not tf_results or not isinstance(tf_results, list):
            return {"error": "empty tf_results", "signal": "HOLD", "confidence": 0.0}

        symbol = str(tf_results[0].get("symbol", "UNKNOWN")).upper()
        direction = str(tf_results[0].get("direction", "LONG")).upper()
        frames = _dedup_str([str(x.get("interval", "?")) for x in tf_results if x])

        avg_rsi = _avg([_get_metric(x, "rsi") for x in tf_results], default=50.0)
        avg_adx = _avg([_get_metric(x, "adx") for x in tf_results], default=20.0)
        avg_volume = _avg(
            [(x.get("volume") if x.get("volume") is not None else _get_metric(x, "volume")) for x in tf_results],
            default=1_000_000.0
        )
        q_scores = []
        for x in tf_results:
            try:
                q_scores.append(float(x.get("quality_score", 0.0) or 0.0))
            except Exception:
                q_scores.append(0.0)
        avg_q = round(sum(q_scores) / len(q_scores), 2) if q_scores else 0.0

        prompt = (
            "You are a professional crypto analyst.\n"
            f"Technical analysis for {symbol} across frames: {', '.join(frames)}\n"
            f"- Direction: {direction}\n"
            f"- Avg RSI: {avg_rsi:.2f}\n"
            f"- Avg ADX: {avg_adx:.2f}\n"
            f"- Avg Volume: {avg_volume:,.0f}\n"
            f"- Avg Quality: {avg_q:.2f}\n\n"
            "Return exactly this format on a single line:\n"
            "Signal: BUY/SELL/HOLD | Confidence: <0-100> | Reason: <short reason>\n"
        )

        logging.info(f"[AI] analyze_with_ai prompt for {symbol} (frames={frames})")
        content = await _safe_chat(
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
            "signal": parsed["signal"],        # BUY/SELL/HOLD
            "confidence": parsed["confidence"],# 0-100
            "raw": content,
            "details": tf_results,
            "reason": parsed.get("reason", ""),
        }
        return result

    except Exception as e:
        logging.error(f"[AI] analyze_with_ai exception: {e}\n{traceback.format_exc()}")
        return {"error": str(e), "signal": "HOLD", "confidence": 0.0}


async def predict_optimal_sl_tp(symbol: str, direction: str, entry_price: float, atr: float = None) -> Tuple[float, float]:
    """
    חישוב SL/TP עם GPT; אם נכשל/לא מפורש → פולבק דטרמיניסטי (calculate_sl_tp).
    """
    try:
        prompt = (
            "You are a crypto trading assistant.\n"
            f"Symbol: {symbol}\n"
            f"Trend: {direction.upper()}\n"
            f"Entry Price: {entry_price}\n"
            f"ATR: {atr if atr is not None else 'N/A'}\n\n"
            "Suggest optimized SL and TP levels based on trend and entry. "
            "Return exactly: SL: <number>, TP: <number>"
        )

        logging.info(f"[AI] SL/TP analysis for {symbol}")
        content = await _safe_chat(
            prompt,
            system="Reply with 'SL: <num>, TP: <num>' only.",
            model=getattr(config, "OPENAI_MODEL", "gpt-4o-mini"),
            temperature=0.2,
            max_tokens=40,
            retries=2,
        )

        m = re.search(r"SL\W*\:\W*([0-9]*\.?[0-9]+)\W*,\W*TP\W*\:\W*([0-9]*\.?[0-9]+)", content or "", re.IGNORECASE)
        if m:
            sl, tp = float(m.group(1)), float(m.group(2))
            return round(sl, 6), round(tp, 6)

        logging.warning(f"[AI] SL/TP parse failed, content={content!r}; using fallback")

    except Exception as e:
        logging.warning(f"[AI-SLTP] Exception: {e}; using fallback")

    # Fallback דטרמיניסטי
    return calculate_sl_tp(entry_price=entry_price, direction=direction, atr=atr)





























