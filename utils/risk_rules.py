# utils/risk_rules.py
from __future__ import annotations
import os
from typing import Dict, Any, Optional

TOP10 = set((os.getenv("TOP10_SYMBOLS","BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,XRPUSDT,ADAUSDT,DOGEUSDT,TRXUSDT,TONUSDT,LTCUSDT")
             .upper().replace(" ","")).split(","))

MIN_RR_TOP10 = float(os.getenv("MIN_RR_TOP10","1.6"))
MIN_RR_ALT   = float(os.getenv("MIN_RR_ALT","1.9"))

# תקרות מינוף לפי משטר תנודתיות
LEV_CAP_LOW  = int(os.getenv("LEV_CAP_VOL_LOW","25"))
LEV_CAP_MID  = int(os.getenv("LEV_CAP_VOL_MID","15"))
LEV_CAP_HIGH = int(os.getenv("LEV_CAP_VOL_HIGH","8"))

# מרחק כניסה מקס' מהמחיר (לא לרדוף)
MAX_ENTRY_GAP_PCT = float(os.getenv("MAX_ENTRY_GAP_PCT","0.35"))  # אחוז

# Kelly “קצוץ”
KELLY_CAP = float(os.getenv("KELLY_CAP","0.15"))  # לעולם לא מעל 15% מההון לטרייד
KELLY_MIN = float(os.getenv("KELLY_MIN","0.01"))  # מינ' 1%

def min_rr_required(symbol: str) -> float:
    return MIN_RR_TOP10 if symbol.upper() in TOP10 else MIN_RR_ALT

def leverage_cap(vol_regime: str) -> int:
    v = (vol_regime or "mid").lower()
    if v == "low":
        return LEV_CAP_LOW
    if v == "high":
        return LEV_CAP_HIGH
    return LEV_CAP_MID

def entry_gap_ok(current_price: float, entry: float) -> bool:
    if not current_price or not entry:
        return True
    gap = abs(entry - current_price) / current_price * 100.0
    return gap <= MAX_ENTRY_GAP_PCT

def kelly_suggestion(success_pct: float, rr: float) -> float:
    """
    Kelly משוער: f* = p - (1-p)/b  (b≈RR)
    תחימה ל-[KELLY_MIN, KELLY_CAP], ולפי הגיון: אם f* שלילי → קח מינ׳ קבוע קטן.
    """
    try:
        p = float(success_pct)/100.0
        b = float(rr)
        if b <= 0:
            return KELLY_MIN
        f = p - (1.0 - p)/b
        f = max(KELLY_MIN, min(KELLY_CAP, f))
        return f
    except Exception:
        return KELLY_MIN

def ensure_tp_sl_with_atr(side: str, price: float, atr: Optional[float], entry: Optional[float], sl: Optional[float], tp: Optional[float]) -> Dict[str, float]:
    """
    אם חסר SL/TP – משלים כללים בסיסיים לפי ATR×1.5 סטופ ו-2R יעד.
    """
    if atr is None or atr <= 0 or not price:
        return {"entry": entry or price, "sl": sl or price, "tp": tp or price}
    entry_eff = entry or price
    risk = 1.5 * atr
    if side.upper() == "LONG":
        sl_eff = sl if sl else (entry_eff - risk)
        tp_eff = tp if tp else (entry_eff + 2*risk)
    else:
        sl_eff = sl if sl else (entry_eff + risk)
        tp_eff = tp if tp else (entry_eff - 2*risk)
    return {"entry": entry_eff, "sl": sl_eff, "tp": tp_eff}

def rr_from_levels(side: str, entry: float, sl: float, tp: float) -> Optional[float]:
    try:
        risk = abs(entry - sl)
        reward = abs(tp - entry)
        if risk <= 0:
            return None
        rr = reward / risk
        return round(rr, 2)
    except Exception:
        return None

def gate_trade(symbol: str, side: str, price: float, entry: float, sl: float, tp: float,
               vol_regime: str, success_pct: Optional[float] = None, leverage: Optional[int] = None) -> Dict[str, Any]:
    """
    גייטינג כללי: RR מינימלי, רודף-מחיר, תקרת מינוף לפי vol_regime. מחזיר dict עם ok/reasons.
    """
    out = {"ok": True, "reasons": [], "caps": {}}
    rr = rr_from_levels(side, entry, sl, tp)
    rr_min = min_rr_required(symbol)
    if rr is None or rr < rr_min:
        out["ok"] = False
        out["reasons"].append(f"rr<{rr_min}")
    if not entry_gap_ok(price, entry):
        out["ok"] = False
        out["reasons"].append("entry_gap")

    lev_cap = leverage_cap(vol_regime)
    out["caps"]["lev_cap"] = lev_cap
    if leverage and leverage > lev_cap:
        out["ok"] = False
        out["reasons"].append(f"lev>{lev_cap}")

    if success_pct is not None and rr is not None:
        f = kelly_suggestion(success_pct, rr)
        out["suggested_budget_frac"] = f

    out["rr"] = rr
    out["rr_min"] = rr_min
    out["vol_regime"] = vol_regime
    return out
