# utils/quality.py  — shim לשם ההיסטורי "utils.quality"
from __future__ import annotations

# ננסה להשתמש במיקום הקאנוני אצלך (quantity_utils)
try:
    from .quantity_utils import compute_quality  # type: ignore
except Exception:
    # Fallback ניטרלי כדי שהאפליקציה תעלה גם אם הקובץ לא נמצא.
    from typing import Optional, Literal, Dict, Any
    Side = Literal["LONG", "SHORT"]

    def compute_quality(
        *,
        symbol: str,
        side: Side,
        entry: Optional[float],
        sl: Optional[float],
        tp: Optional[float],
        leverage: int,
        budget: float,
        anchor,
        atr: Optional[float] = None,
    ) -> Dict[str, Any]:
        return {
            "quality_score": 5.0,
            "success_pct": 50.0,
            "components": {
                "note": "fallback shim: utils.quantity_utils.compute_quality not found",
                "symbol": symbol, "side": side, "entry": entry, "sl": sl, "tp": tp,
            },
        }

__all__ = ["compute_quality"]
