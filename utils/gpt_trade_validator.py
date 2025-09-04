# utils/gpt_trade_validator.py
from __future__ import annotations
import os, logging
from typing import Dict, Any

logger = logging.getLogger("algogpt.gpt_validator")

# פלאגין אימות “רך” — לא מפיל לולאות. מחזיר always-ok עם שדות הסבר.
# אפשר להחליף מאוחר יותר באינטגרציה ל-OpenAI (כבר יש /ai/quality במערכת).
def validate_proposal(tp: Dict[str, Any]) -> Dict[str, Any]:
    """
    tp: {
      symbol, side, entry, sl, tp1, tp2?, tp3?, leverage, interval, atr?, adx?, rsi?, macd_hist?, volume?
    }
    """
    out = {"ok": True, "reasons": []}
    try:
        rr = None
        entry = float(tp.get("entry", 0))
        sl = float(tp.get("sl", 0))
        tp1 = float(tp.get("tp1", 0))
        if entry <= 0 or sl <= 0 or tp1 <= 0:
            out["ok"] = False
            out["reasons"].append("entry/sl/tp1 must be > 0")
            return out

        side = (tp.get("side","LONG") or "LONG").upper()
        if side == "LONG":
            rr = (tp1 - entry) / (entry - sl) if (entry - sl) != 0 else 0
            if sl >= entry:
                out["ok"] = False
                out["reasons"].append("SL must be below entry for LONG")
        else:
            rr = (entry - tp1) / (sl - entry) if (sl - entry) != 0 else 0
            if sl <= entry:
                out["ok"] = False
                out["reasons"].append("SL must be above entry for SHORT")

        if rr is not None and rr < float(os.getenv("APPROVAL_RR_MIN", "1.30")):
            out["ok"] = False
            out["reasons"].append(f"RR too low ({rr:.2f})")

        # סינון אינדיקטורים בסיסי — לא מחייב
        adx = float(tp.get("adx", 0) or 0)
        if adx and adx < 18:
            out["reasons"].append("ADX weak (<18)")

        return out
    except Exception as e:
        logger.warning(f"validate_proposal soft-error: {e}")
        return {"ok": True, "reasons": ["validator_soft_error"]}
