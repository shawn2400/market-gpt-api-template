# utils/anchor.py
from __future__ import annotations
import os
import logging
from dataclasses import dataclass
from typing import Literal, Tuple, List

Side = Literal["LONG", "SHORT"]

logger = logging.getLogger("algogpt.anchor")

@dataclass
class AnchorDecision:
    mode_requested: str   # off / soft / hard
    mode_applied: str     # off / soft / hard
    bias: str             # bull / bear / neutral
    score: float          # 0-100
    allow: bool           # האם לאפשר טרייד
    severity: str         # none / weak / strong
    reason: str           # הסבר

def _env_float(key: str, default: float) -> float:
    v = os.getenv(key, "")
    v = v.strip() if isinstance(v, str) else ""
    try:
        return float(v) if v else default
    except Exception:
        return default

def _env_list(key: str, default: str) -> List[str]:
    raw = os.getenv(key, default) or default
    return [x.strip() for x in str(raw).split(",") if str(x).strip()]

def _get_anchor_mode() -> str:
    mode = (os.getenv("BTC_ANCHOR_MODE", "") or "").strip().lower()
    if not mode:
        enforce = (os.getenv("BTC_ANCHOR_ENFORCE", "false") or "").strip().lower() == "true"
        return "hard" if enforce else "soft"
    return mode if mode in {"off", "soft", "hard"} else "soft"

def _get_anchor_reading() -> Tuple[str, float]:
    """
    כאן אפשר להחליף בעתיד למימוש אמיתי שמחשב RSI/EMA על BTCUSDT.
    כרגע: אם מוגדר BTC_ANCHOR_FORCE → נשתמש בו.
    """
    forced = (os.getenv("BTC_ANCHOR_FORCE", "") or "").strip().lower()
    if forced:
        try:
            if ":" in forced:
                b, s = forced.split(":", 1)
                bias = b.strip()
                score = float(s.strip())
            else:
                bias = forced
                score = 0.0
            if bias not in {"bull", "bear", "neutral"}:
                bias = "neutral"
            score = max(0.0, min(100.0, score))
            return bias, score
        except Exception:
            return "neutral", 0.0
    return "neutral", 0.0

def evaluate_anchor(side: Side) -> AnchorDecision:
    mode_req = _get_anchor_mode()  # off / soft / hard
    frames = _env_list("BTC_ANCHOR_FRAMES", "15m,1h")
    strong_th = _env_float("BTC_ANCHOR_STRONG_TH", 70.0)
    weak_th   = _env_float("BTC_ANCHOR_WEAK_TH",   55.0)

    bias, score = _get_anchor_reading()
    conflict = ((side == "LONG" and bias == "bear") or (side == "SHORT" and bias == "bull"))

    if mode_req == "off":
        decision = AnchorDecision("off", "off", bias, score, True, "none", "Anchor disabled")
    elif bias == "neutral" or score <= weak_th:
        decision = AnchorDecision(
            mode_req, mode_req, bias, score, True,
            "none" if bias == "neutral" else "weak",
            f"Anchor {bias} ({score:.1f}) on frames {frames}; no strong conflict"
        )
    elif conflict:
        if score >= strong_th:
            decision = AnchorDecision(
                mode_req, "hard", bias, score, False, "strong",
                f"Strong conflict with BTC anchor ({bias} {score:.1f}≥{strong_th}); HARD block"
            )
        elif mode_req == "hard":
            decision = AnchorDecision(
                "hard", "hard", bias, score, False, "weak",
                f"Conflict with BTC anchor ({bias} {score:.1f}); HARD mode blocks"
            )
        else:
            decision = AnchorDecision(
                "soft", "soft", bias, score, True, "weak",
                f"Conflict with BTC anchor ({bias} {score:.1f}); SOFT mode allows with warning"
            )
    else:
        decision = AnchorDecision(
            mode_req, mode_req, bias, score, True, "none",
            f"Aligned with BTC anchor ({bias} {score:.1f})"
        )

    # ✅ Structured JSON log
    logger.info({
        "event": "anchor_decision",
        "side": side,
        "mode_requested": decision.mode_requested,
        "mode_applied": decision.mode_applied,
        "bias": decision.bias,
        "score": decision.score,
        "allow": decision.allow,
        "severity": decision.severity,
        "reason": decision.reason,
    })

    return decision

__all__ = ["AnchorDecision", "evaluate_anchor"]








