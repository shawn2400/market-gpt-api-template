# utils/anchor.py
from __future__ import annotations

# שכבה דקה שמייצאת הלאה את ה-API הקיים של עוגן ה-BTC
# כך שאפשר לייבא תמיד `from utils.anchor import evaluate_anchor, AnchorDecision`
# בלי תלות בשם הקובץ הפנימי.

from .btc_anchor import evaluate_anchor, AnchorDecision  # re-export
try:
    # אופציונלי: אם הגדרת Side ב-btc_anchor
    from .btc_anchor import Side  # type: ignore
except Exception:  # pragma: no cover
    Side = None  # לשקט טיפוסי

__all__ = ["evaluate_anchor", "AnchorDecision", "Side"]





