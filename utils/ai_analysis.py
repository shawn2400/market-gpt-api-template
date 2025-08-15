# utils/ai_analysis.py
from __future__ import annotations

import os
import logging
import re
import traceback
import asyncio
from typing import Tuple, List, Dict, Any, Optional

# --- config (עם פולבק ל-ENV אם המודול לא קיים) ---
try:
    from utils import config  # type: ignore
    _OPENAI_MODEL = getattr(config, "OPENAI_MODEL", os.getenv("OPENAI_MODEL", "gpt-4o-mini"))
    _OPENAI_TIMEOUT = float(getattr(config, "OPENAI_TIMEOUT_SECONDS", os.getenv("OPENAI_TIMEOUT_SECONDS", "30.0")))
except Exception:
    _OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    _OPENAI_TIMEOUT = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "30.0"))

from utils.ai_client import chat
from utils.sl_tp_utils import calculate_sl_tp

# --- עוגן BTC ---
from utils.btc_anchor import (
    compute_btc_anchor,
    anchor_gate,
    sltp_multipliers,
)

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
    מצפה בדיוק לפורמט:
      Signal: BUY/SELL/HOLD | Confidence: <0-100> | Reason: <short>
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
            out["reason"] = _truncate(m_reason.group(1).strip(), 240)
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
            model=(model or _OPENAI_MODEL),
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
async def analyze_with_ai(
    tf_results: List[Dict[str, Any]],
    *,
    use_anchor: bool = True,
    anchor_frames: Optional[List[str]] = None,
    anchor_market: str = "futures",
    btc_anchor: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    קולט פלט multi_tf_scan (לסמל יחיד, מסגרות זמן שונות) ומחזיר החלטה מרוכזת.
    משלב 'עוגן BTC' (חי) להטיה/חסימה/בוסט – עם קאש קצר בצד העוגן.
    """
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

        # --- עוגן BTC (חי/מועבר) ---
        anchor_used: Optional[Dict[str, Any]] = None
        if use_anchor:
            if btc_anchor is not None:
                anchor_used = btc_anchor
            else:
                afr = anchor_frames or (frames if frames else ["15m", "1h"])
                anchor_used = await compute_btc_anchor(frames=afr, market=anchor_market)

        # --- Prompt ל-GPT (עם קונטקסט של העוגן) ---
        anchor_line = ""
        if anchor_used:
            anchor_line = (
                f"- BTC Anchor: dir={anchor_used.get('direction')}, "
                f"strength={anchor_used.get('strength')}, frames={','.join(anchor_used.get('frames', []))}\n"
            )

        prompt = (
            "You are a professional crypto analyst.\n"
            f"Technical analysis for {symbol} across frames: {', '.join(frames)}\n"
            f"- Direction: {direction}\n"
            f"- Avg RSI: {avg_rsi:.2f}\n"
            f"- Avg ADX: {avg_adx:.2f}\n"
            f"- Avg Volume: {avg_volume:,.0f}\n"
            f"- Avg Quality: {avg_q:.2f}\n"
            f"{anchor_line}\n"
            "Return exactly this format on a single line:\n"
            "Signal: BUY/SELL/HOLD | Confidence: <0-100> | Reason: <short reason>\n"
        )

        logging.info(f"[AI] analyze_with_ai prompt for {symbol} (frames={frames})")
        content = await _safe_chat(
            prompt,
            system="Be concise and deterministic. No markdown.",
            model=_OPENAI_MODEL,
            temperature=0.0,
            max_tokens=200,
            timeout_sec=_OPENAI_TIMEOUT,
        )

        parsed = _parse_signal_conf(content)
        signal = parsed["signal"]
        confidence = int(round(parsed["confidence"]))
        reason = parsed.get("reason", "")

        # --- Gate/Boost מול BTC (דטרמיניסטי) ---
        if anchor_used:
            gate = anchor_gate(direction, anchor_used)
            if gate["action"] == "block":
                signal = "HOLD"
                confidence = min(confidence, 40)
                reason = (reason + "; " if reason else "") + f"blocked by BTC ({gate['reason']})"
            elif gate["action"] == "downgrade":
                confidence = max(0, confidence - int(gate.get("penalty", 15)))
                reason = (reason + "; " if reason else "") + gate["reason"]
            elif gate["action"] == "boost":
                confidence = min(100, confidence + int(gate.get("bonus", 10)))
                reason = (reason + "; " if reason else "") + gate["reason"]

        result: Dict[str, Any] = {
            "symbol": symbol,
            "direction": direction,
            "quality_score": avg_q,
            "frames": frames,
            "signal": signal,
            "confidence": int(confidence),
            "raw": content,
            "details": tf_results,
            "reason": reason,
        }
        if anchor_used:
            result["anchor"] = {
                "direction": anchor_used.get("direction"),
                "strength": anchor_used.get("strength"),
                "trend": anchor_used.get("trend"),
                "frames": anchor_used.get("frames"),
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
    *,
    use_anchor: bool = True,
    anchor_frames: Optional[List[str]] = None,
    anchor_market: str = "futures",
    btc_anchor: Optional[Dict[str, Any]] = None,
) -> Tuple[float, float]:
    """
    חישוב SL/TP עם GPT; אם נכשל/לא מפורש → פולבק דטרמיניסטי (calculate_sl_tp).
    משלב כוונון לפי עוגן BTC עבור כל אופציה (גם GPT וגם פולבק).
    """
    sl_val: Optional[float] = None
    tp_val: Optional[float] = None

    # 1) ננסה GPT
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
            model=_OPENAI_MODEL,
            temperature=0.2,
            max_tokens=40,
            timeout_sec=min(20.0, _OPENAI_TIMEOUT),
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
    except Exception as e:
        logging.warning(f"[AI-SLTP] Exception: {e}; will fallback if needed")

    # 2) פולבק אם GPT לא נתן תשובה טובה
    if not (sl_val and tp_val and sl_val > 0 and tp_val > 0):
        sl_val, tp_val = calculate_sl_tp(entry_price=entry_price, direction=direction, atr=atr)

    # 3) כוונון לפי עוגן BTC (עם קאש בצד העוגן)
    try:
        if use_anchor:
            anchor_used = btc_anchor or await compute_btc_anchor(
                frames=(anchor_frames or ["15m", "1h"]),
                market=anchor_market,
            )
            sl_mult, tp_mult = sltp_multipliers(direction, anchor_used)
            if direction.upper() == "LONG":
                sl_dist = abs(entry_price - sl_val) * sl_mult
                tp_dist = abs(tp_val - entry_price) * tp_mult
                sl_val = entry_price - sl_dist
                tp_val = entry_price + tp_dist
            else:  # SHORT
                sl_dist = abs(sl_val - entry_price) * sl_mult
                tp_dist = abs(entry_price - tp_val) * tp_mult
                sl_val = entry_price + sl_dist
                tp_val = entry_price - tp_dist
    except Exception as e:
        logging.warning(f"[AI-SLTP] anchor adjust failed: {e}")

    return round(float(sl_val), 6), round(float(tp_val), 6)


































