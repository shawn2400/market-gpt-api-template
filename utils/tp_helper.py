# utils/tp_helper.py
from __future__ import annotations
import os, re, time, logging, asyncio
from typing import List, Optional, Dict, Any, Tuple
from utils.binance_client import (
    place_tp_ladder, set_breakeven_stop
)

logger = logging.getLogger("algogpt.tp_helper")

# ENV flags
LADDER_TP_ENABLE = os.getenv("LADDER_TP_ENABLE", "1") == "1"
TP_LADDER_ON_APPROVE = os.getenv("TP_LADDER_ON_APPROVE", "1") == "1"

STREAM_TP_BE = os.getenv("STREAM_TP_BE", "true").lower() in ("1","true","yes")
TP_BE_OFFSET_BPS = float(os.getenv("TP_BE_OFFSET_BPS", "5"))  # 0.05%
TP_BE_ONLY_AFTER_TP1 = os.getenv("TP_BE_ONLY_AFTER_TP1", "1") == "1"

# Defaults for ladder (from ENV binance_client already uses)
ENV_TP_PCTS = os.getenv("LADDER_TP_DEFAULT_PCTS", "1.8,3.2,5.5")
ENV_TP_SPLITS = os.getenv("LADDER_TP_DEFAULT_SPLITS", "0.4,0.35,0.25")

# Idempotency: avoid duplicate ladder per symbol in short window
_last_ladder_at: Dict[str, float] = {}
_LADDER_COOLDOWN_SEC = 60.0

def _now() -> float:
    return time.time()

def _parse_tp_pcts_from_text(text: str) -> List[float]:
    """
    מחפש תבניות כמו: TP1=+1.8% | TP2=+3.2% | TP3=+5.5%
    מחזיר [1.8, 3.2, 5.5] אם מצא, אחרת [].
    """
    if not text:
        return []
    # אחוזים אחרי "TP" כלשהו
    pcts: List[float] = []
    # קודם חפש TPn=+x.x%
    for m in re.finditer(r"TP\d+\s*=\s*\+?(-?\d+(?:\.\d+)?)\s*%", text, re.IGNORECASE):
        try:
            pcts.append(float(m.group(1)))
        except:
            pass
    # אם לא מצא, חפש כל אחוז בסמיכות למילה TP
    if not pcts:
        for m in re.finditer(r"(?:TP\d*[^0-9\-+]{0,8})?(\+?-?\d+(?:\.\d+)?)\s*%", text, re.IGNORECASE):
            try:
                val = float(m.group(1))
                if val > 0:
                    pcts.append(val)
            except:
                pass
    # הסר כפילויות/שטויות
    pcts = [x for x in pcts if x > 0]
    # סדר עולה
    pcts.sort()
    return pcts

def _env_list_of_floats(csv_str: str) -> List[float]:
    out: List[float] = []
    for part in (csv_str or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(float(part))
        except:
            pass
    return out

def _deduce_tp_inputs(decision: Dict[str, Any], tp_pcts: Optional[List[float]], splits: Optional[List[float]]) -> Tuple[List[float], List[float]]:
    # 1) מהפרמטרים הישירים
    if tp_pcts and len(tp_pcts) > 0:
        tp = tp_pcts[:]
    else:
        # 2) נסה לפרש מהטקסט (ai_summary / message)
        text = decision.get("ai_summary") or decision.get("message") or decision.get("text") or ""
        parsed = _parse_tp_pcts_from_text(text)
        if parsed:
            tp = parsed
        else:
            # 3) מה-ENV
            tp = _env_list_of_floats(ENV_TP_PCTS)
            if not tp:
                tp = [1.8, 3.2, 5.5]
    # splits
    sp = splits[:] if splits else _env_list_of_floats(ENV_TP_SPLITS)
    if not sp:
        sp = [0.4, 0.35, 0.25]
    return tp, sp

def _ladder_cooldown_ok(symbol: str) -> bool:
    t = _last_ladder_at.get(symbol.upper(), 0.0)
    if _now() - t < _LADDER_COOLDOWN_SEC:
        return False
    _last_ladder_at[symbol.upper()] = _now()
    return True

# ------------------- Public APIs -------------------

def on_approve_trade(decision: Dict[str, Any], tp_pcts: Optional[List[float]] = None, splits: Optional[List[float]] = None) -> Dict[str, Any]:
    """
    נקרא אחרי אישור ✅ בטלגרם.
    decision: מצופה לכלול לפחות symbol, side. אם יש ai_summary עם TP אחוזים – ינסה לפרש.
    """
    symbol = (decision.get("symbol") or "").upper()
    if not symbol:
        return {"ok": False, "error": "missing symbol"}

    if not TP_LADDER_ON_APPROVE or not LADDER_TP_ENABLE:
        logger.info("[tp_helper] Ladder disabled by env (symbol=%s)", symbol)
        return {"ok": True, "skipped": True, "reason": "disabled"}

    if not _ladder_cooldown_ok(symbol):
        return {"ok": True, "skipped": True, "reason": "cooldown"}

    tp, sp = _deduce_tp_inputs(decision, tp_pcts, splits)
    logger.info("[tp_helper] placing ladder for %s (tp=%s, splits=%s)", symbol, tp, sp)
    return place_tp_ladder(symbol, percent_targets=tp, splits=sp)

def on_tp1_hit(symbol: str) -> Dict[str, Any]:
    """
    נקרא כאשר זוהה מילוי TP1 בפוזיציה פעילה. יזיז SL ל-BE (+offset).
    """
    if not STREAM_TP_BE or not TP_BE_ONLY_AFTER_TP1:
        return {"ok": True, "skipped": True, "reason": "be_disabled"}
    try:
        resp = set_breakeven_stop(symbol, offset_bps=TP_BE_OFFSET_BPS)
        return {"ok": True, "action": "be_set", "resp": resp}
    except Exception as e:
        logger.error("on_tp1_hit failed: %s", e)
        return {"ok": False, "error": str(e)}

# ------------------- Async wrappers (אם קוראים מתוך FastAPI/async) -------------------

async def on_approve_trade_async(decision: Dict[str, Any], tp_pcts: Optional[List[float]] = None, splits: Optional[List[float]] = None) -> Dict[str, Any]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: on_approve_trade(decision, tp_pcts, splits))

async def on_tp1_hit_async(symbol: str) -> Dict[str, Any]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: on_tp1_hit(symbol))
