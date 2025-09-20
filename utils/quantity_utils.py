# utils/quantity_utils.py
from __future__ import annotations

def round_step(value: float, step: float) -> float:
    """
    עיגול ערך לפי stepSize (LOT_SIZE) של הסימבול.
    שומר יציבות נקודת ציפה ועוקף שגיאות קירוב.
    """
    if not step:
        return float(value)
    v = float(value)
    s = float(step)
    # round to nearest multiple of step
    n = round(v / s)
    return round(n * s, 12)

__all__ = ["round_step"]















