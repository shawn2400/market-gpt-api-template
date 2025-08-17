# utils/time_to_target.py
from __future__ import annotations
from typing import Dict, Any, Optional

_TF_MINUTES = {
    "1m":1, "3m":3, "5m":5, "15m":15, "30m":30,
    "1h":60, "2h":120, "4h":240, "6h":360, "8h":480, "12h":720,
    "1d":1440
}

def eta_to_target(*, entry: float, tp: float, sl: float, atr: float, timeframe: str) -> Dict[str, Any]:
    """
    הערכת זמן (בדקות) לפי יחס מרחק / ATR.
    """
    tf_min = _TF_MINUTES.get(timeframe, 15)
    def _mins(dist: float) -> Optional[float]:
        try:
            bars = max(0.2, dist / max(atr, 1e-9))  # לא פחות מחמישית בר
            return round(bars * tf_min, 2)
        except Exception:
            return None

    dist_tp = abs(tp - entry)
    dist_sl = abs(entry - sl)
    eta_tp = _mins(dist_tp)
    eta_sl = _mins(dist_sl)

    note = "scalp" if (eta_tp and eta_tp <= 30) else ("swing" if (eta_tp and eta_tp >= 180) else "intraday")
    return {"ok": True, "eta_tp_minutes": eta_tp, "eta_sl_minutes": eta_sl, "speed_note": note}

