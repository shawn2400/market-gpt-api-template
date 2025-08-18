# utils/scoring.py
from __future__ import annotations
import os
from typing import Dict, Tuple

def _env_float(name: str, default: float) -> float:
    try:
        return float(str(os.getenv(name, str(default))).strip())
    except Exception:
        return default

W_QS   = _env_float("DECISION_W_QUALITY", 0.40)
W_SP   = _env_float("DECISION_W_SUCCESS", 0.25)
W_ETA  = _env_float("DECISION_W_SPEED",   0.15)
W_VOL  = _env_float("DECISION_W_VOLAT",   0.10)
W_CORR = _env_float("DECISION_W_DECORR",  0.10)

def weights_norm() -> Tuple[float, float, float, float, float]:
    s = max(1e-9, W_QS + W_SP + W_ETA + W_VOL + W_CORR)
    return (W_QS/s, W_SP/s, W_ETA/s, W_VOL/s, W_CORR/s)

try:
    from utils.quality_score import compute_quality_score  # type: ignore
except Exception:
    def compute_quality_score(_: object) -> float:
        return 0.0

def decision_score(components: Dict[str, object]) -> float:
    qs   = float(components.get("quality_score", 0.0) or 0.0)
    rr   = float(components.get("rr",             0.0) or 0.0)
    eta  = float(components.get("eta_score",      0.0) or 0.0)
    vol  = float(components.get("volume_score",   0.0) or 0.0)
    corr = float(components.get("corr_score",     0.0) or 0.0)
    w_qs, w_sp, w_eta, w_vol, w_corr = weights_norm()
    score = (w_qs*qs) + (w_sp*rr) + (w_eta*eta) + (w_vol*vol) + (w_corr*corr)
    return float(round(score, 6))

__all__ = ["weights_norm", "compute_quality_score", "decision_score"]




