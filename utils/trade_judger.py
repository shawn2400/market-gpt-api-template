# utils/trade_judger.py
from __future__ import annotations
import math, logging
from typing import Dict, Any, Optional

logger = logging.getLogger("algogpt.trade_judger")

def _safe(v, d=0.0) -> float:
    try: return float(v)
    except Exception: return float(d)

def judge_pretrade(*,
                   symbol: str,
                   side: str,
                   entry: float,
                   sl: float,
                   tp: float,
                   atr_abs: Optional[float] = None,
                   adx_val: Optional[float] = None,
                   mom_hint: Optional[float] = None) -> Dict[str, Any]:
    """
    ציון טרייד לפני כניסה — 0..100:
      - Risk/Reward (40%)
      - מרחקים ביחס ל-ATR (30%)
      - מומנטום/ADX (30%)
    קלטי ATR/ADX אופציונליים — אם לא קיימים, מקבל נטרלי.
    """
    s = symbol.upper().strip()
    sd = side.upper().strip()
    e = _safe(entry); slp = _safe(sl); tpp = _safe(tp)

    if e <= 0 or tpp <= 0 or slp <= 0:
        return {"ok": False, "symbol": s, "error": "invalid_prices"}

    # RR
    if sd == "BUY":
        reward = max(tpp - e, 1e-9)
        risk   = max(e - slp, 1e-9)
    else:
        reward = max(e - tpp, 1e-9)
        risk   = max(slp - e, 1e-9)

    rr = reward / max(risk, 1e-9)
    rr_score = max(0.0, min(1.0, (rr - 1.0) / 2.0))  # RR=1 → 0, RR=3 → ~1
    rr_score100 = 100.0 * rr_score

    # ATR distances (נעדיף SL≈0.8..1.8 ATR, TP≈2..5 ATR)
    sl_atr = None if not atr_abs or atr_abs <= 0 else abs(e - slp) / atr_abs
    tp_atr = None if not atr_abs or atr_abs <= 0 else abs(tpp - e) / atr_abs
    def _bucket(x: Optional[float], lo: float, hi: float) -> float:
        if x is None: return 0.6  # נטרלי
        if x < lo:    return max(0.0, x/lo*0.7)
        if x > hi:    return max(0.0, (hi/x)*0.8)
        # sweet spot
        return 1.0

    sl_score = _bucket(sl_atr, 0.8, 1.8)
    tp_score = _bucket(tp_atr, 2.0, 5.0)
    atr_score100 = 100.0 * (0.5*sl_score + 0.5*tp_score)

    # Momentum / ADX
    # ADX>25 טוב, <15 חלש; mom_hint>0 טוב לקנייה, <0 טוב למכירה
    adx_s = 0.6 if adx_val is None else (1.0 if adx_val >= 25 else (0.3 if adx_val <= 15 else 0.7))
    if mom_hint is None:
        mom_s = 0.6
    else:
        if sd == "BUY":
            mom_s = 1.0 if mom_hint > 0 else 0.3
        else:
            mom_s = 1.0 if mom_hint < 0 else 0.3
    mom_score100 = 100.0 * (0.6*adx_s + 0.4*mom_s)

    # משקולות
    total = 0.4*rr_score100 + 0.3*atr_score100 + 0.3*mom_score100
    reasons = []
    if rr < 1.3: reasons.append("RR<1.3")
    if sl_atr and (sl_atr < 0.6 or sl_atr > 2.5): reasons.append(f"SL_ATR={sl_atr:.2f}")
    if tp_atr and tp_atr < 1.5: reasons.append(f"TP_ATR={tp_atr:.2f}")
    if adx_val is not None and adx_val < 18: reasons.append(f"ADX={adx_val:.1f}")

    return {
        "ok": True,
        "symbol": s,
        "side": sd,
        "score": round(total, 1),
        "components": {
            "rr_score": round(rr_score100, 1),
            "atr_score": round(atr_score100, 1),
            "mom_score": round(mom_score100, 1),
        },
        "rr": round(rr, 3),
        "atr_dist": {"sl_atr": sl_atr, "tp_atr": tp_atr},
        "adx": adx_val,
        "mom_hint": mom_hint,
        "reasons": reasons,
    }
