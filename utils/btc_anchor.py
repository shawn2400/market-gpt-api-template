# utils/anchor.py
from __future__ import annotations
import os
from dataclasses import dataclass
from typing import Literal

Side = Literal["LONG", "SHORT"]

@dataclass
class AnchorDecision:
    mode_requested: str
    mode_applied: str
    bias: str
    score: float
    allow: bool
    severity: str
    reason: str

def _env_float(key: str, default: float) -> float:
    v = os.getenv(key, "").strip()
    try:
        return float(v) if v else default
    except Exception:
        return default

def _env_list(key: str, default: str) -> list[str]:
    raw = os.getenv(key, default)
    return [x.strip() for x in raw.split(",") if x.strip()]

def _get_anchor_mode() -> str:
    mode = os.getenv("BTC_ANCHOR_MODE", "").strip().lower()
    if not mode:
        enforce = os.getenv("BTC_ANCHOR_ENFORCE", "false").strip().lower() == "true"
        return "hard" if enforce else "soft"
    return mode if mode in {"off","soft","hard"} else "soft"

def _get_anchor_reading() -> tuple[str, float]:
    forced = os.getenv("BTC_ANCHOR_FORCE", "").strip().lower()
    if forced:
        try:
            if ":" in forced:
                b, s = forced.split(":", 1)
                bias = b.strip()
                score = float(s.strip())
            else:
                bias = forced
                score = 0.0
            if bias not in {"bull","bear","neutral"}:
                bias = "neutral"
            score = max(0.0, min(100.0, score))
            return bias, score
        except Exception:
            return "neutral", 0.0
    return "neutral", 0.0  # TODO: לחבר למקור נתונים אמיתי

def evaluate_anchor(side: Side) -> AnchorDecision:
    mode_req = _get_anchor_mode()
    frames = _env_list("BTC_ANCHOR_FRAMES", "15m,1h")
    strong_th = _env_float("BTC_ANCHOR_STRONG_TH", 70.0)
    weak_th   = _env_float("BTC_ANCHOR_WEAK_TH",   55.0)

    bias, score = _get_anchor_reading()
    conflict = ((side=="LONG" and bias=="bear") or (side=="SHORT" and bias=="bull"))

    if mode_req == "off":
        return AnchorDecision("off","off",bias,score,True,"none","Anchor disabled")

    if bias == "neutral" or score <= weak_th:
        return AnchorDecision(mode_req,mode_req,bias,score,True,"none" if bias=="neutral" else "weak",
                              f"Anchor {bias} ({score:.1f}) on frames {frames}; no strong conflict")

    if conflict:
        if score >= strong_th:
            return AnchorDecision(mode_req,"hard",bias,score,False,"strong",
                                  f"Strong conflict with BTC anchor ({bias} {score:.1f}≥{strong_th}); HARD block")
        if mode_req == "hard":
            return AnchorDecision("hard","hard",bias,score,False,"weak",
                                  f"Conflict with BTC anchor ({bias} {score:.1f}); HARD mode blocks")
        return AnchorDecision("soft","soft",bias,score,True,"weak",
                              f"Conflict with BTC anchor ({bias} {score:.1f}); SOFT mode allows with warning")

    return AnchorDecision(mode_req,mode_req,bias,score,True,"none",
                          f"Aligned with BTC anchor ({bias} {score:.1f})")





