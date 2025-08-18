# utils/scoring.py
from __future__ import annotations
import os

def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)).strip())
    except Exception:
        return default

# משקלים (ניתן לשנות ב-.env)
W_QS   = _env_float("DECISION_W_QUALITY", 0.40)
W_SP   = _env_float("DECISION_W_SUCCESS", 0.25)
W_ETA  = _env_float("DECISION_W_SPEED",   0.15)
W_VOL  = _env_float("DECISION_W_VOLAT",   0.10)
W_CORR = _env_float("DECISION_W_DECORR",  0.10)

def weights_norm() -> tuple[float, float, float, float, float]:
    s = max(1e-9, W_QS + W_SP + W_ETA + W_VOL + W_CORR)
    return (W_QS/s, W_SP/s, W_ETA/s, W_VOL/s, W_CORR/s)


