# utils/ai_analysis.py
import logging
import re
import traceback
from typing import Tuple, List, Dict, Any, Optional

from utils import config
from utils.ai_client import chat
from utils.sl_tp_utils import calculate_sl_tp

# ---------------------- Utilities ----------------------
def _avg(vals, default: float = 0.0) -> float:
    xs: List[float] = []
    for v in (vals or []):
        try:
            if v is None:
                continue
            xs.append(float(v))
        except Exception:
            continue
    return round(sum(xs) / len(xs), 4) if xs else float(default)

def _clamp(v: float, lo: float, hi: float) -> float:
    try:
        v = float(v)
    except Exception:
        v = lo
    return max(lo, min(hi, v))

def _dedup_str(seq: List[str]) -> List[str]:
    seen: set = set()
    out: List[str] = []
    for s in (seq or []):
        if not s:
            continue
        s2 = str(s).strip()
        if s2 and s2 not in seen:
            seen.add(s2)
            out.append(s2)
    return out

def _truncate(s: str, max_len: int) -> str:
    if not isinstance(s, str):
        return ""
    return s if len(s) <= max_len else (s[: max_len - 3] + "...")

# ---------------------- Parse helpers ----------------------
_SIG_RE = re.compile(r"Signal\W*:\W*(BUY|SELL|HOLD)", re.IGNORECASE)
_CONF_RE = re.compile(r"Confidence\W*:\W*([0-9]+(?:\.[0-9]+)?)\s*%?", re.IGNORECASE)
_REASON_RE = re.compile(r"Reason\W*:\W*(.+)$", re.IGNORECASE)

def _parse_signal_conf(text: str) -> Dict[str, Any]:
    """
    מצפה לפורמט:
      Signal: BUY/SELL/HOLD | Confidence: <0-100> | Reason: <short>
    מחזיר ברירת מחדל בטוחה במקרה חריג.
    """
    out = {"signal": "HOLD", "confidence": 0.0, "reason": ""}
    if not isinstance(text, str) or not text.strip():
        return out

    try:
        m_sig = _SIG_RE.search(text)
        if m_sig:
            out["signal"] = m_sig.group(1).upper()

        m_conf = _CONF_RE.search(text)
        if m_conf:
            out["confidence"] = _clamp(m_conf.group(1), 0.0, 100.0)

        m_reason = _REASON_RE.search(text)
        if m_reason:
            reason = m_reason.group(1).strip()
            out["reason"] = _truncate(reason, 240)
    except Exception:
        pass

    if out["signal"] not in ("BUY", "SELL", "HOLD"):
        out["signal"] = "HOLD"
    out["confidence"] = _clamp(out["confidence"], 0.0, 100.0)
    return out

def _get_metric(d: Dict[str, Any], key: str):
    if key in d:
        return d.get(key)
    inds = d.get("indicators") or {}
    return inds.get(key)

# ---------------------- Safe AI call ----------------------
import asyncio

async def _safe_chat(
    prompt: str,
    *,
    system: str,
    model: Optional[str],
    temperature: float,
    max_tokens: int,
    timeout_sec: float = 20.0,
    **kwargs,
) -> str:
    """
    מעטפת בטוחה ל-chat: קיטום prompt, timeout קשיח, ולוג שגיאות;
    מחזירה מחרוזת ריקה במקרה תקלה.
    """
    try:
        prompt = _truncate(prompt, 6000)
        coro = chat(
            prompt,
            system=system,
            model=model or getattr(config, "OPENAI_MODEL", "gpt-4o-mini"),
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )
        return await asyncio.wait_for(coro, timeout=timeout_sec)
    except asyncio.TimeoutError:
        logging.warning("[AI] chat timeout")
        return ""
    except Exception as e:
        logging.error(f"[AI] chat failed: {e}")
        return ""

# ---------------------- Public API ----------------------
async def analyze_with_ai(tf_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """קולט פלט multi_tf_scan (לסמל יחיד, מסגרות זמן שונות) ומחזיר החלטה מרוכזת."""
    try:
        if not tf_results or not isinstance(tf_results, list):
            return {"error": "empty tf_results", "signal": "HOLD", "confidence": 0.0}

        first = tf_results[0] or {}
        symbol = str(first.get("symbol", "UNKNOWN")).upper()
        direction = str(first.get("direction", "LONG")).upper()

        frames = _dedup_str([str(x.get("interval", "?")) for x in tf_results if isinstance(x, dict)])[:6]

        avg_rsi = _avg([_get_metric(x, "rsi") for x in tf_results], default=50.0)
        avg_adx = _avg([_get_metric(x, "adx") for x in tf_results], default=20.0)
        avg_volume = _avg([(x.get("volume") if isinstance(x, dict) else None) for x in tf_results], default=1_000_000.0)

        q_scores: List[float] = []
        for x in tf_results:
            try:
                q_scores.append(float((x or {}).get("quality_score", 0.0) or 0.0))
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
            timeout_sec=float(getattr(config, "OPENAI_TIMEOUT_SECONDS", 30.0)),
        )

        parsed = _parse_signal_conf(content)

        result = {
            "symbol": symbol,
            "direction": direction,
            "quality_score": avg_q,
            "frames": frames,
            "signal": parsed["signal"],          # BUY/SELL/HOLD
            "confidence": parsed["confidence"],  # 0-100
            "raw": content,
            "details": tf_results,
            "reason": parsed.get("reason", ""),
        }
        return result

    except Exception as e:
        logging.error(f"[AI] analyze_with_ai exception: {e}\n{traceback.format_exc()}")
        return {"error": str(e), "signal": "HOLD", "confidence": 0.0}

async def predict_optimal_sl_tp(
    symbol: str,
    direction: str,
    entry_price: float,
    atr: Optional[float] = None,
) -> Tuple[float, float]:
    """
    חישוב SL/TP עם GPT; אם נכשל/לא מפורש → פולבק דטרמיניסטי (calculate_sl_tp).
    כולל הגנות ערכים לפי כיוון (LONG/SHORT).
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
            timeout_sec=min(20.0, float(getattr(config, "OPENAI_TIMEOUT_SECONDS", 30.0))),
        )

        m = re.search(r"SL\W*:\W*([0-9]*\.?[0-9]+)\W*,\W*TP\W*:\W*([0-9]*\.?[0-9]+)", content or "", re.IGNORECASE)
        if m:
            sl_val, tp_val = float(m.group(1)), float(m.group(2))
            if sl_val > 0 and tp_val > 0:
                if direction.upper() == "LONG":
                    if tp_val < entry_price:
                        tp_val = entry_price * 1.003
                    if sl_val > entry_price:
                        sl_val = entry_price * 0.997
                elif direction.upper() == "SHORT":
                    if tp_val > entry_price:
                        tp_val = entry_price * 0.997
                    if sl_val < entry_price:
                        sl_val = entry_price * 1.003
                return round(sl_val, 6), round(tp_val, 6)

        logging.warning(f"[AI] SL/TP parse failed, content={content!r}; using fallback")

    except Exception as e:
        logging.warning(f"[AI-SLTP] Exception: {e}; using fallback")

    return calculate_sl_tp(entry_price=entry_price, direction=direction, atr=atr)
































