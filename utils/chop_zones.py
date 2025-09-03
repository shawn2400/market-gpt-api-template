# utils/chop_zones.py
from __future__ import annotations
import pandas as pd
import numpy as np

def detect_chop_zones(df: pd.DataFrame, adx_col: str = "adx", max_adx: float = 18.0, min_bars: int = 6) -> list[tuple[int, int]]:
    """
    מזהה אזורי Chop לפי סף ADX והאורך המינימלי.
    מחזיר רשימת טווחים: [(start_idx, end_idx), ...]
    """
    if df is None or df.empty or adx_col not in df:
        return []

    adx = df[adx_col].fillna(100.0).values
    zones = []
    start = None
    for i, v in enumerate(adx):
        if v <= max_adx:
            if start is None:
                start = i
        else:
            if start is not None and i - start >= min_bars:
                zones.append((start, i - 1))
            start = None
    if start is not None and len(adx) - start >= min_bars:
        zones.append((start, len(adx) - 1))
    return zones


