# utils/scoring.py
from __future__ import annotations

import os
from typing import Dict, Tuple

# ------------------------------------------------------------
# Env helpers
# ------------------------------------------------------------

def _env_float(name: str, default: float) -> float:
    """
    קורא משתנה סביבה כ-float עם ברירת מחדל בטוחה.
    """
    try:
        return float(str(os.getenv(name, str(default))).strip())
    except Exception:
        return default

# ------------------------------------------------------------
# Weights (configurable via ENV)
# ------------------------------------------------------------

# משקלים בסיסיים שניתנים לכיול מה-ENV
W_QS   = _env_float("DECISION_W_QUALITY", 0.40)  # איכות האות הכוללת
W_SP   = _env_float("DECISION_W_SUCCESS", 0.25)  # RR / success proxy
W_ETA  = _env_float("DECISION_W_SPEED",   0.15)  # מהירות/זמן להזדמנות
W_VOL  = _env_float("DECISION_W_VOLAT",   0.10)  # תנודתיות/נפח
W_CORR = _env_float("DECISION_W_DECORR",  0.10)  # דקורלציה/תלות ב-BTC

def weights_norm() -> Tuple[float, float, float, float, float]:
    """
    מחזיר את המשקלים מנורמלים כך שסכומם 1.0.
    """
    s = max(1e-9, W_QS + W_SP + W_ETA + W_VOL + W_CORR)
    return (W_QS / s, W_SP / s, W_ETA / s, W_VOL / s, W_CORR / s)

# ------------------------------------------------------------
# Optional bridge to quality score
# ------------------------------------------------------------

try:
    # אם קיימת אצלך פונקציה מרכזית לחישוב איכות — נשתמש בה במידת הצורך
    from utils.quality_score import compute_quality_score  # type: ignore
except Exception:
    def compute_quality_score(_: object) -> float:  # fallback בטוח
        return 0.0

# ------------------------------------------------------------
# Decision score
# ------------------------------------------------------------

def decision_score(components: Dict[str, object]) -> float:
    """
    ציון החלטה משוקלל לפי רכיבים שמגיעים מהסריקה/AI.
    מפתחי קלט נפוצים:
      - quality_score: float
      - rr: float (Risk/Reward)
      - eta_score: float (מהירות/זמינות)
      - volume_score: float
      - corr_score: float (דקורלציה/תלות ב-BTC)

    החישוב אינו מפיל את המערכת אם חסר ערך — הכל עם ברירות מחדל 0.0.
    """
    # שליפת ערכים עם ברירות מחדל בטוחות
    qs   = float(components.get("quality_score", 0.0) or 0.0)
    rr   = float(components.get("rr",             0.0) or 0.0)
    eta  = float(components.get("eta_score",      0.0) or 0.0)
    vol  = float(components.get("volume_score",   0.0) or 0.0)
    corr = float(components.get("corr_score",     0.0) or 0.0)

    w_qs, w_sp, w_eta, w_vol, w_corr = weights_norm()
    score = (w_qs * qs) + (w_sp * rr) + (w_eta * eta) + (w_vol * vol) + (w_corr * corr)
    return float(round(score, 6))

__all__ = [
    "weights_norm",
    "compute_quality_score",
    "decision_score",
]



