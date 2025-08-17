# utils/anchor.py
from __future__ import annotations
import os
from dataclasses import dataclass
from typing import Literal, Optional, Dict, Any

Side = Literal["LONG", "SHORT"]

@dataclass
class AnchorDecision:
    mode_requested: str          # off / soft / hard
    mode_applied: str            # off / soft / hard (לאחר הסלמה אוטומטית אם צריך)
    bias: str                    # bull / bear / neutral
    score: float                 # 0-100 עוצמת בייס
    allow: bool                  # האם לאפשר טרייד
    severity: str                # none / weak / strong
    reason: str                  # הסבר קריא

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
    # off / soft / hard
    mode = os.getenv("BTC_ANCHOR_MODE", "").strip().lower()
    if not mode:
        # תאימות לאחור:
        enforce = os.getenv("BTC_ANCHOR_ENFORCE", "false").strip().lower() == "true"
        return "hard" if enforce else "soft"
    if mode not in {"off", "soft", "hard"}:
        return "soft"
    return mode

def _get_anchor_reading() -> tuple[str, float]:
    """
    השג קריאת עוגן BTC: (bias, score).
    bias: bull/bear/neutral, score: 0-100.
    *** חשוב ***: הנקודה הזו אמורה להיות מוזנת ממנוע השוק שלך.
    כרגע נתמכות 2 אפשרויות:
    1) משתנה ENV "BTC_ANCHOR_FORCE" בפורמט "bull:75" / "bear:60" / "neutral:0"
    2) ברירת מחדל: neutral,0 (לא חוסם)
    """
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
            if bias not in {"bull", "bear", "neutral"}:
                bias = "neutral"
            score = max(0.0, min(100.0, score))
            return bias, score
        except Exception:
            return "neutral", 0.0
    # TODO: לחבר כאן מקור דאטה אמיתי (WS/REST) לחישוב הבייס והסקור
    return "neutral", 0.0

def evaluate_anchor(side: Side) -> AnchorDecision:
    """
    סינון SOFT→HARD:
    - STRONG_TH: אם קונפליקט חזק → הסלמה ל-HARD וחסימה.
    - WEAK_TH:   אם קונפליקט חלש/בינוני → מצב SOFT רק מתריע (לא חוסם).
    """
    mode_req = _get_anchor_mode()           # off/soft/hard
    frames = _env_list("BTC_ANCHOR_FRAMES", "15m,1h")
    strong_th = _env_float("BTC_ANCHOR_STRONG_TH", 70.0)
    weak_th   = _env_float("BTC_ANCHOR_WEAK_TH",   55.0)

    bias, score = _get_anchor_reading()     # bull/bear/neutral, 0-100

    # קביעה אם יש קונפליקט בין כיוון הטרייד לעוגן
    conflict = (
        (side == "LONG" and bias == "bear") or
        (side == "SHORT" and bias == "bull")
    )

    if mode_req == "off":
        return AnchorDecision(
            mode_requested="off", mode_applied="off",
            bias=bias, score=score, allow=True, severity="none",
            reason="Anchor disabled"
        )

    if bias == "neutral" or score <= weak_th:
        # ניטרלי/חלש: ב-SOFT נתיר, ב-HARD גם נתיר (אין קייס חוסם)
        return AnchorDecision(
            mode_requested=mode_req, mode_applied=mode_req,
            bias=bias, score=score, allow=True, severity="none" if bias=="neutral" else "weak",
            reason=f"Anchor {bias} ({score:.1f}) on frames {frames}; no strong conflict"
        )

    if conflict:
        # יש קונפליקט: אם מעל strong_th → הסלמה ל-HARD וחסימה
        if score >= strong_th:
            return AnchorDecision(
                mode_requested=mode_req, mode_applied="hard",
                bias=bias, score=score, allow=False, severity="strong",
                reason=f"Strong conflict with BTC anchor ({bias} {score:.1f}≥{strong_th}); HARD block"
            )
        # קונפליקט בינוני: ב-SOFT מתריעים (לא חוסם), ב-HARD יחסום
        if mode_req == "hard":
            return AnchorDecision(
                mode_requested="hard", mode_applied="hard",
                bias=bias, score=score, allow=False, severity="weak",
                reason=f"Conflict with BTC anchor ({bias} {score:.1f}); HARD mode blocks"
            )
        return AnchorDecision(
            mode_requested="soft", mode_applied="soft",
            bias=bias, score=score, allow=True, severity="weak",
            reason=f"Conflict with BTC anchor ({bias} {score:.1f}); SOFT mode allows with warning"
        )

    # אין קונפליקט (alignment): תמיד נתיר
    return AnchorDecision(
        mode_requested=mode_req, mode_applied=mode_req,
        bias=bias, score=score, allow=True, severity="none",
        reason=f"Aligned with BTC anchor ({bias} {score:.1f})"
    )






