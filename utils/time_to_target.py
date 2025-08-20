# utils/time_to_target.py
from __future__ import annotations
from typing import Dict, Any, Optional

_MINUTES = {
    "1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30,
    "1h": 60, "2h": 120, "4h": 240, "6h": 360, "8h": 480, "12h": 720,
    "1d": 1440,
}

def _mins(tf: str) -> int:
    return int(_MINUTES.get(tf, 15))

def eta_by_atr(
    *, entry: float, tp: float, sl: float, atr: float, timeframe: str
) -> Dict[str, Any]:
    """
    אומדן לינארי: זמן ≈ (מרחק יעד / ATR) * משך־בר (בדקות).
    """
    if entry <= 0 or atr is None or atr <= 0:
        return {"ok": False, "eta_tp_minutes": None, "eta_sl_minutes": None, "speed_note": "missing/invalid inputs"}

    d_tp = abs(tp - entry)
    d_sl = abs(entry - sl)
    bars_tp = d_tp / atr
    bars_sl = d_sl / atr
    m = _mins(timeframe)
    eta_tp = bars_tp * m
    eta_sl = bars_sl * m

    note = "scalp" if eta_tp <= 45 else ("swing" if eta_tp >= 6*60 else "intra")
    return {
        "ok": True,
        "eta_tp_minutes": round(float(eta_tp), 1),
        "eta_sl_minutes": round(float(eta_sl), 1),
        "speed_note": note,
    }

# ✅ alias לשם שה־routes מצפה לו
eta_to_target = eta_by_atr


