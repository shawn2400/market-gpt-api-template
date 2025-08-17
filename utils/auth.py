# utils/anchor.py
from __future__ import annotations
import os
from dataclasses import dataclass
from typing import Literal, Tuple, List

Side = Literal["LONG", "SHORT"]

# ================================================================
# נסה להשתמש במימוש הרשמי מ-utils/btc_anchor; אם אין/חסר → Fallback
# ================================================================
try:
    from .btc_anchor import AnchorDecision as _AD, evaluate_anchor as _evaluate_anchor  # type: ignore

    AnchorDecision = _AD  # re-export

    def evaluate_anchor(side: Side) -> _AD:
        """Proxy ל-implementation הרשמי ב-btc_anchor (אם זמין)."""
        return _evaluate_anchor(side)

except Exception:
    # -----------------------------
    # Fallback-compatible implementation
    # -----------------------------
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
        """
        מחזיר את מצב העוגן:
        - BTC_ANCHOR_MODE: off/soft/hard
        - תאימות לאחור: BTC_ANCHOR_ENFORCE=true → hard, אחרת soft
        """
        mode = (os.getenv("BTC_ANCHOR_MODE", "") or "").strip().lower()
        if not mode:
            enforce = (os.getenv("BTC_ANCHOR_ENFORCE", "false") or "").strip().lower() == "true"
            return "hard" if enforce else "soft"
        return mode if mode in {"off", "soft", "hard"} else "soft"

    def _get_anchor_reading() -> Tuple[str, float]:
        """
        מקור קריאת העוגן (fallback):
        - DEV/בדיקות: BTC_ANCHOR_FORCE="bull:75" / "bear:60" / "neutral:0"
        - PROD: מחזיר neutral:0 אם אין מקור חיצוני.
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
        # כאן ניתן לחבר מנגנון אמיתי (WS/REST) אם תרצה בעתיד
        return "neutral", 0.0

    def evaluate_anchor(side: Side) -> AnchorDecision:
        """
        לוגיקת Anchor (fallback):
        - מצב ברירת מחדל: soft
        - התנגשות חזקה (>= STRONG_TH) מסלימה ל-hard וחוסמת
        - סף חלש (<= WEAK_TH) מאפשר (עם/בלי אזהרה)
        """
        mode_req = _get_anchor_mode()  # off / soft / hard
        frames = _env_list("BTC_ANCHOR_FRAMES", "15m,1h")
        strong_th = _env_float("BTC_ANCHOR_STRONG_TH", 70.0)
        weak_th   = _env_float("BTC_ANCHOR_WEAK_TH",   55.0)

        bias, score = _get_anchor_reading()
        conflict = ((side == "LONG" and bias == "bear") or (side == "SHORT" and bias == "bull"))

        if mode_req == "off":
            return AnchorDecision("off", "off", bias, score, True, "none", "Anchor disabled")

        if bias == "neutral" or score <= weak_th:
            return AnchorDecision(
                mode_req, mode_req, bias, score, True,
                "none" if bias == "neutral" else "weak",
                f"Anchor {bias} ({score:.1f}) on frames {frames}; no strong conflict"
            )

        if conflict:
            if score >= strong_th:
                return AnchorDecision(
                    mode_req, "hard", bias, score, False, "strong",
                    f"Strong conflict with BTC anchor ({bias} {score:.1f}≥{strong_th}); HARD block"
                )
            if mode_req == "hard":
                return AnchorDecision(
                    "hard", "hard", bias, score, False, "weak",
                    f"Conflict with BTC anchor ({bias} {score:.1f}); HARD mode blocks"
                )
            return AnchorDecision(
                "soft", "soft", bias, score, True, "weak",
                f"Conflict with BTC anchor ({bias} {score:.1f}); SOFT mode allows with warning"
            )

        return AnchorDecision(
            mode_req, mode_req, bias, score, True, "none",
            f"Aligned with BTC anchor ({bias} {score:.1f})"
        )

# יצוא מפורש
__all__ = ["AnchorDecision", "evaluate_anchor"]









