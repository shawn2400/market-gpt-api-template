# utils/ai_risk_filter.py
from __future__ import annotations
import os
from typing import Dict, Any

# מסנן סיכונים מבוסס חוקים קלים — עובד מהר, לא חוסם לולאות.
# (אפשר לשלב עם /ai/quality של המערכת שלך לאימות כפול)
def quick_risk_gate(tp: Dict[str, Any]) -> Dict[str, Any]:
    """
    tp: {
      "symbol","side","entry","sl","tp1","leverage","spread_bps","funding_bps","vol_usdt","adx","atr","rsi","macd_hist"
    }
    """
    res = {"ok": True, "reasons": []}
    try:
        vol = float(tp.get("vol_usdt", 0))
        if vol and vol < float(os.getenv("MIN_VOLUME", "1000000")):
            res["ok"] = False
            res["reasons"].append("low_volume")

        spread = float(tp.get("spread_bps", 0))
        if spread and spread > float(os.getenv("SOP_MAX_SPREAD_BPS", "3.0")):
            res["ok"] = False
            res["reasons"].append("wide_spread")

        adx = float(tp.get("adx", 0) or 0)
        if adx and adx < float(os.getenv("CHOP_ADX_MAX","18")):
            # לא מפיל — רק אזהרה, כי אתה ביקשת “לא לפספס”; עדיין נציין
            res["reasons"].append("chop_risk_adx")

        # יחס TP/SL מינ' — לא לפסוח
        entry = float(tp.get("entry", 0))
        sl    = float(tp.get("sl", 0))
        tp1   = float(tp.get("tp1", 0))
        if entry > 0 and sl > 0 and tp1 > 0:
            if tp.get("side","LONG").upper()=="LONG":
                rr = (tp1 - entry) / (entry - sl) if (entry - sl)!=0 else 0
            else:
                rr = (entry - tp1) / (sl - entry) if (sl - entry)!=0 else 0
            if rr < float(os.getenv("APPROVAL_RR_MIN","1.30")):
                res["ok"] = False
                res["reasons"].append("rr_low")

        return res
    except Exception:
        return {"ok": True, "reasons": ["risk_gate_soft_error"]}
