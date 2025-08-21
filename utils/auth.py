# utils/anchor.py
from dataclasses import dataclass
from typing import Literal
import random

@dataclass
class AnchorDecision:
    mode_requested: Literal["LONG","SHORT"]
    mode_applied: Literal["LONG","SHORT"]
    bias: str
    score: float
    allow: bool
    severity: str
    reason: str

def evaluate_anchor(side: str) -> AnchorDecision:
    """
    מעריך Anchor פשוט (אפשר לחבר בהמשך לאינדיקטורים אמיתיים).
    כרגע — סימולציה עם bias=NEUTRAL/UP/DOWN.
    """
    bias = random.choice(["UP", "DOWN", "NEUTRAL"])
    score = round(random.uniform(0, 100), 2)
    allow = (score >= 50)
    return AnchorDecision(
        mode_requested=side,
        mode_applied=side,
        bias=bias,
        score=score,
        allow=allow,
        severity="high" if not allow else "low",
        reason=f"Simulated decision bias={bias}, score={score}"
    )




































