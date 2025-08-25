# utils/anchor.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal
import logging

from utils.watchlist_utils import load_watchlist

logger = logging.getLogger("algogpt.anchor")

AnchorMode = Literal["off", "soft", "hard"]

@dataclass
class AnchorDecision:
    mode_requested: AnchorMode
    mode_applied: AnchorMode
    bias: str              # "BULLISH" / "BEARISH" / "NEUTRAL"
    score: float
    allow: bool
    severity: str
    reason: str

def evaluate_anchor(side: str, mode: AnchorMode = "soft") -> AnchorDecision:
    """
    מעריך Anchor לפי BTCUSDT כבסיס.
    side: "LONG" או "SHORT"
    mode: "off" / "soft" / "hard"
    """
    side = str(side).upper()
    if side not in ("LONG", "SHORT"):
        raise ValueError(f"invalid side: {side}")

    # --- Anchor disabled
    if mode == "off":
        return AnchorDecision(
            mode_requested=mode,
            mode_applied="off",
            bias="NEUTRAL",
            score=50.0,
            allow=True,
            severity="NONE",
            reason="Anchor disabled",
        )

    bias, score = "NEUTRAL", 50.0
    try:
        watchlist = load_watchlist()
        btc = next((it for it in watchlist if it.get("symbol") == "BTCUSDT"), None)
        if btc:
            bias = "BULLISH" if str(btc.get("direction")).upper() == "LONG" else "BEARISH"
            score = float(btc.get("quality_score") or 5) * 10  # מדרג 0–100
    except Exception as e:
        logger.warning("⚠️ Anchor evaluation failed: %s", e)

    # --- החלטה
    allow, severity, reason = True, "LOW", "Bias allows trade"

    if mode == "soft":
        if side == "LONG" and bias == "BEARISH":
            allow, severity, reason = False, "MEDIUM", "Soft-block: Bearish bias vs LONG"
        elif side == "SHORT" and bias == "BULLISH":
            allow, severity, reason = False, "MEDIUM", "Soft-block: Bullish bias vs SHORT"

    elif mode == "hard":
        if bias == "NEUTRAL":
            allow, severity, reason = False, "HIGH", "Hard-block: Neutral bias"
        elif side == "LONG" and bias == "BEARISH":
            allow, severity, reason = False, "HIGH", "Hard-block: Bearish bias vs LONG"
        elif side == "SHORT" and bias == "BULLISH":
            allow, severity, reason = False, "HIGH", "Hard-block: Bullish bias vs SHORT"

    return AnchorDecision(
        mode_requested=mode,
        mode_applied=mode,
        bias=bias,
        score=score,
        allow=allow,
        severity=severity,
        reason=reason,
    )












