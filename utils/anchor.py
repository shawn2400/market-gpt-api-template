# utils/anchor.py
import math
from dataclasses import dataclass
from typing import Optional, Literal

from utils.indicators import ema, rsi
from utils.watchlist_utils import load_watchlist

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
    side = side.upper()
    if side not in ("LONG", "SHORT"):
        raise ValueError(f"invalid side: {side}")

    # ברירת מחדל אם אין Anchor
    if mode == "off":
        return AnchorDecision(
            mode_requested=mode,
            mode_applied="off",
            bias="NEUTRAL",
            score=50.0,
            allow=True,
            severity="NONE",
            reason="Anchor disabled"
        )

    # 🚩 כאן נכניס לוגיקה פשוטה (אפשר לשפר לפי אינדיקטורים אמתיים)
    try:
        watchlist = load_watchlist()
        btc = next((it for it in watchlist if it["symbol"] == "BTCUSDT"), None)
        if not btc:
            raise RuntimeError("BTCUSDT not found in watchlist")

        bias = "BULLISH" if btc.get("direction") == "LONG" else "BEARISH"
        score = float(btc.get("quality_score", 6)) * 10  # מדרג 0–100
    except Exception:
        bias, score = "NEUTRAL", 50.0

    # החלטה אם לאפשר
    allow = True
    severity = "LOW"
    reason = "Bias allows trade"

    if mode == "soft":
        if side == "LONG" and bias == "BEARISH":
            allow, severity, reason = False, "MEDIUM", "Soft-block: Bearish bias vs LONG"
        if side == "SHORT" and bias == "BULLISH":
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











