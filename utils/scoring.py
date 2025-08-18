# utils/scoring.py
from __future__ import annotations
import os
from typing import Dict, Any, Tuple

def _env_float(name: str, default: float) -> float:
    try:
        return float(str(os.getenv(name, str(default))).strip())
    except Exception:
        return default

# משקלים (ניתן לשנות ב-.env)
W_QS   = _env_float("DECISION_W_QUALITY", 0.40)
W_SP   = _env_float("DECISION_W_SUCCESS", 0.25)
W_ETA  = _env_float("DECISION_W_SPEED",   0.15)
W_VOL  = _env_float("DECISION_W_VOLAT",   0.10)
W_CORR = _env_float("DECISION_W_DECORR",  0.10)

def weights_norm() -> Tuple[float, float, float, float, float]:
    s = max(1e-9, W_QS + W_SP + W_ETA + W_VOL + W_CORR)
    return (W_QS/s, W_SP/s, W_ETA/s, W_VOL/s, W_CORR/s)

def _clip01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))

def decision_score(components: Dict[str, Any]) -> float:
    """
    קלט מחושב מ-/decision/best-trades או מחולל אחר.
    מרכיבים נתמכים (לא חובה כולם):
      - quality  או quality_score: 0..10
      - success_pct: 0..100
      - eta_minutes: נמוך=טוב
      - volatility:  מספר חיובי; נמוך=טוב
      - corr_to_btc: -1..+1 (עצמאות=טוב => |corr| קטן)
    פלט: ציון 0..10
    """
    w_q, w_sp, w_eta, w_vol, w_corr = weights_norm()

    q = float(components.get("quality", components.get("quality_score", 0.0)))
    quality_s = _clip01(q / 10.0)

    sp = components.get("success_pct", None)
    success_s = _clip01((float(sp) if sp is not None else 55.0) / 100.0)

    eta = components.get("eta_minutes", None)
    # מהיר יותר=טוב; סולם רך סביב 30 דק'
    eta_s = _clip01(1.0 / (1.0 + max(0.0, float(eta)) / 30.0)) if eta is not None else 0.5

    vol = components.get("volatility", None)
    # תנודתיות נמוכה עדיפה ברירתית; סולם רך סביב 2.0
    vol_s = _clip01(1.0 / (1.0 + max(0.0, float(vol)) / 2.0)) if vol is not None else 0.5

    corr = components.get("corr_to_btc", None)
    decorr_s = _clip01(1.0 - abs(float(corr))) if corr is not None else 0.5

    score01 = (quality_s*w_q + success_s*w_sp + eta_s*w_eta + vol_s*w_vol + decorr_s*w_corr)
    return round(score01 * 10.0, 2)





