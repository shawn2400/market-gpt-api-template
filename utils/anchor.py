# utils/anchor.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal, Tuple
import logging
import os

from utils.watchlist_utils import load_watchlist

logger = logging.getLogger("algogpt.anchor")

AnchorMode = Literal["off", "soft", "hard"]
Bias = Literal["bull", "bear", "neutral"]

@dataclass
class AnchorDecision:
    mode_requested: AnchorMode
    mode_applied: AnchorMode
    bias: Bias                 # "bull" | "bear" | "neutral"
    score: float               # 0..100
    allow: bool
    severity: str
    reason: str

def _infer_btc_bias() -> Tuple[Bias, float]:
    """
    מחלץ כיוון ו"עוצמה" (0..100) לפי BTCUSDT מתוך ה-watchlist.
    אם אין נתון — מחזיר neutral, 50.
    """
    try:
        wl = load_watchlist()
        btc = next((it for it in wl if str(it.get("symbol")).upper() == "BTCUSDT"), None)
        if not btc:
            return "neutral", 50.0
        direction = str(btc.get("direction", "")).upper()
        bias: Bias = "bull" if direction == "LONG" else ("bear" if direction == "SHORT" else "neutral")
        q = btc.get("quality_score")
        score = float(q) * 10.0 if isinstance(q, (int, float)) else 50.0
        score = max(0.0, min(100.0, score))
        return bias, score
    except Exception as e:
        logger.warning("Anchor: failed to infer BTC bias: %s", e)
        return "neutral", 50.0

def evaluate_anchor(side: str, mode: AnchorMode | None = None) -> AnchorDecision:
    """
    מעריך Anchor לפי BTCUSDT כעוגן.
    side: "LONG" או "SHORT" (הטרייד המבוקש).
    mode: "off" / "soft" / "hard" (אם None, נלקח מ־ENV ANCHOR_MODE, דיפולט soft).

    לוגיקה:
      - off  : לא חוסם, bias=neutral/נלמד, allow=True תמיד.
      - soft : חוסם בעדינות כשיש סתירה עם הביאס (allow=False, severity=MEDIUM).
      - hard : חוסם בכל ניטרליות או סתירה (severity=HIGH).
    """
    s = str(side).upper().strip()
    if s not in ("LONG", "SHORT"):
        raise ValueError(f"invalid side: {side}")

    mode_env = (mode or os.getenv("ANCHOR_MODE", "soft")).lower()
    if mode_env not in ("off", "soft", "hard"):
        mode_env = "soft"

    bias, score = _infer_btc_bias()

    # ברירת מחדל
    allow, severity, reason = True, "LOW", "bias allows trade"

    if mode_env == "off":
        return AnchorDecision(mode_requested=mode_env, mode_applied="off", bias=bias,
                              score=score, allow=True, severity="NONE", reason="anchor disabled")

    conflict = (s == "LONG" and bias == "bear") or (s == "SHORT" and bias == "bull")
    neutral  = (bias == "neutral")

    if mode_env == "soft":
        if conflict:
            allow, severity, reason = False, "MEDIUM", f"soft-block: trade {s} vs bias {bias}"
    else:  # hard
        if neutral:
            allow, severity, reason = False, "HIGH", "hard-block: neutral bias"
        elif conflict:
            allow, severity, reason = False, "HIGH", f"hard-block: trade {s} vs bias {bias}"

    return AnchorDecision(
        mode_requested=mode_env,
        mode_applied=mode_env,
        bias=bias,
        score=score,
        allow=allow,
        severity=severity,
        reason=reason,
    )













