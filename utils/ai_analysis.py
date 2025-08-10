# utils/ai_analysis.py
import logging
import re
import json
import traceback
from typing import Tuple, List, Dict, Any, Optional

from utils import config
from utils.ai_client import chat
from utils.sl_tp_utils import calculate_sl_tp


def _avg(vals, default: float = 0.0) -> float:
    xs = [float(v) for v in vals if isinstance(v, (int, float))]
    return round(sum(xs) / len(xs), 4) if xs else float(default)


def _parse_signal_conf_text(text: str) -> Dict[str, Any]:
    """
    פולבק לפרסינג טקסט חופשי בתבנית:
    'Signal: BUY/SELL/HOLD | Confidence: <num>% | Reason: ...'
    """
    out = {"signal": "HOLD", "confidence": 0.0, "reason": ""}
    if not isinstance(text, str):
        return out
    try:
        m_sig = re.search(r"Signal:\s*(BUY|SELL|HOLD)", text, re.IGNORECASE)
        if m_sig:
            out["signal"] = m_sig.group(1).upper()
        m_conf = re.search(r"Confidence:\s*(\d+(\.\d+)?)", text)
        if m_conf:
            out["confidence"] = float(m_conf.group(1))
        m_reason = re.search(r"Reason:\s*(.+)$", text, re.IGNORECASE)
        if m_reason:
            out["reason"] = m_reason.group(1).strip()
    except Exception:
        pass
    return out


def _sanitize_signal(sig: Optional[str]) -> str:
    s = (sig or "").strip().upper()
    return s if s in ("BUY", "SELL", "HOLD") else "HOLD"


def _clamp_confidence(x: Any) -> float:
    try:
        v = float(x)
    except Exception:
        return 0.0
    if v < 0:
        return 0.0
    if v > 100:
        return 100.0
    return round(v, 2)


def _valid_sltp(direction: str, entry: float, sl: float, tp: float) -> bool:
    d = (direction or "").upper()
    try:
        e, s, t = float(entry), float(sl), float(tp)
    except Exception:
        return False
    if d == "LONG":
        return s < e < t
    if d == "SHORT":
        return t < e < s
    return False


async def analyze_with_ai(tf_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    קולט פלט multi_tf_scan עבור סימבול יחיד במספר טיימפריימים,
    ומחזיר החלטת AI קשיחה: {symbol, direction, quality_score, frames, signal, confidence, reason, raw, details}
    הבאנו JSON-mode כברירת מחדל + פולבק לפרסינג טקסטואלי.
    """
    try:
        if not tf_results or not isinstance(tf_results, list):
            return {"error": "empty tf_results", "signal": "HOLD", "confidence": 0.0}

        symbol = str(tf_results[0].get("symbol", "UNKNOWN")).upper()
        direction = str(tf_results[0].get("direction", "LONG")).upper()
        frames = [str(x.get("interval", "?")) for x in tf_results if x and isinstance(x, dict)]
        # דה-דופליקציה ושמירה על סדר
        seen, frames = set(), [f for f in frames if not (f in seen or seen.add(f))]

        avg_rsi = _avg([x.get("rsi") for x in tf_results], default=50.0)
        avg_adx = _avg([x.get("adx") for x in tf_results], default=20.0)
        avg_volume = _avg([x.get("volume") for x in tf_results], default=1_000_000.0)
        q_scores = [float(x.get("quality_score", 0.0)) for x in tf_results if isinstance(x, dict)]
        avg_q = round(sum(q_scores) / len(q_scores), 2) if q_scores else 0.0

        # — נסיון ראשון: JSON-mode —
        sys = (
            "You are a professional crypto analyst. "
            "Be concise and deterministic. Respond as strict JSON only."
        )
        user = (
            f"Technical analysis for {symbol} across frames: {', '.join(frames)}\n"
            f"- Direction: {direction}\n"
            f"- Avg RSI: {avg_rsi:.2f}\n"
            f"- Avg ADX: {avg_adx:.2f}\n"
            f"- Avg Volume: {avg_volume:,.0f}\n"
            f"- Avg Quality: {avg_q:.2f}\n\n"
            f"Return a JSON object with keys: "
            f"signal (BUY/SELL/HOLD), confidence (0-100 number), reason (<=120 chars)."
        )

        content = await chat(
            user,
            system=sys,
            model=getattr(config, "OPENAI_MODEL", "gpt-4o-mini"),
            temperature=0.0,
            max_tokens=200,
            retries=2,
            json_mode=True,  # ← JSON-mode (במודלים התומכים)
        )

        parsed: Dict[str, Any] = {}
        try:
            parsed = json.loads(content) if isinstance(content, str) else {}
        except Exception:
            parsed = {}

        if not isinstance(parsed, dict) or not parsed:
            # פולבק לטקסט חופשי
            parsed = _parse_signal_conf_text(content)

        signal = _sanitize_signal(parsed.get("signal"))
        confidence = _clamp_confidence(parsed.get("confidence", 0.0))
        reason = (parsed.get("reason") or "").strip()
        if len(reason) > 120:
            reason = reason[:117] + "..."

        result = {
            "symbol": symbol,
            "direction": direction,
            "quality_score": avg_q,
            "frames": frames,
            "signal": signal,
            "confidence": confidence,
            "reason": reason,
            "raw": content,
            "details": tf_results,
        }
        return result

    except Exception as e:
        logging.error(f"[AI] analyze_with_ai exception: {e}\n{traceback.format_exc()}")
        return {"error": str(e), "signal": "HOLD", "confidence": 0.0}


async def predict_optimal_sl_tp(
    symbol: str,
    direction: str,
    entry_price: float,
    atr: float = None
) -> Tuple[float, float]:
    """
    חישוב SL/TP בעזרת GPT (JSON-mode) עם פולבק דטרמיניסטי (calculate_sl_tp).
    מבצע ולידציה בסיסית שהערכים על הצד הנכון של המחיר בהתאם לכיוון.
    """
    try:
        diru = (direction or "LONG").upper()
        sys = (
            "You are a crypto trading assistant. "
            "Respond as strict JSON only."
        )
        user = (
            f"Symbol: {symbol}\n"
            f"Trend: {diru}\n"
            f"Entry Price: {entry_price}\n"
            f"ATR: {atr if atr is not None else 'N/A'}\n\n"
            f"Suggest optimized stop-loss and take-profit levels.\n"
            f"Return a JSON object: {{\"sl\": <number>, \"tp\": <number>}}"
        )

        # ניסיון ראשון: JSON-mode
        content = await chat(
            user,
            system=sys,
            model=getattr(config, "OPENAI_MODEL", "gpt-4o-mini"),
            temperature=0.2,
            max_tokens=60,
            retries=2,
            json_mode=True,
        )

        sl: Optional[float] = None
        tp: Optional[float] = None

        try:
            obj = json.loads(content) if isinstance(content, str) else {}
            if isinstance(obj, dict):
                if isinstance(obj.get("sl"), (int, float)) and isinstance(obj.get("tp"), (int, float)):
                    sl, tp = float(obj["sl"]), float(obj["tp"])
        except Exception:
            sl = tp = None

        # פולבק לפרסינג טקסטואלי "SL: <num>, TP: <num>"
        if sl is None or tp is None:
            m = re.search(r"SL:\s*([0-9]*\.?[0-9]+)\s*,\s*TP:\s*([0-9]*\.?[0-9]+)", str(content))
            if m:
                sl, tp = float(m.group(1)), float(m.group(2))

        # אם עדיין אין תקין → פולבק דטרמיניסטי
        if sl is None or tp is None:
            logging.warning(f"[AI] SL/TP parse failed, content={content!r}; using fallback")
            return calculate_sl_tp(entry_price=entry_price, direction=direction, atr=atr)

        # ולידציה/תיקון בסיסי
        if not _valid_sltp(diru, float(entry_price), sl, tp):
            logging.warning(f"[AI] SL/TP invalid for {symbol} dir={diru}: entry={entry_price}, sl={sl}, tp={tp}; fallback")
            return calculate_sl_tp(entry_price=entry_price, direction=direction, atr=atr)

        return (round(float(sl), 6), round(float(tp), 6))

    except Exception as e:
        logging.warning(f"[AI-SLTP] Exception: {e}; using fallback")
        return calculate_sl_tp(entry_price=entry_price, direction=direction, atr=atr)


























