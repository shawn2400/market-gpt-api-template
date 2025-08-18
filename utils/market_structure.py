from __future__ import annotations
from typing import List, Tuple
import pandas as pd
import numpy as np

def _pivot_mask_max(s: pd.Series, span: int) -> pd.Series:
    return (s == s.rolling(span, center=True, min_periods=1).max())

def _pivot_mask_min(s: pd.Series, span: int) -> pd.Series:
    return (s == s.rolling(span, center=True, min_periods=1).min())

def _last_two(arr: List[Tuple[int, float]]) -> List[Tuple[int, float]]:
    return arr[-2:] if len(arr) >= 2 else arr

def add_market_structure_columns(
    df: pd.DataFrame,
    *,
    ms_lookback: int = 5,
    ms_pivot_span: int = 3,
    high_col: str = "high",
    low_col: str = "low",
) -> pd.DataFrame:
    """
    מוסיף:
      - ms_label: HH/HL/LH/LL על סמך שני שיאים ושני שפלים אחרונים
      - ms_trend: UP/DOWN/RANGE נגזר מה-label
    """
    if df is None or df.empty:
        d = pd.DataFrame(index=(df.index if df is not None else None))
        d["ms_label"] = ""
        d["ms_trend"] = "RANGE"
        return d

    d = df.copy()
    if high_col not in d.columns or low_col not in d.columns:
        d["ms_label"] = ""
        d["ms_trend"] = "RANGE"
        return d

    high = pd.to_numeric(d[high_col], errors="coerce")
    low  = pd.to_numeric(d[low_col],  errors="coerce")

    ph = _pivot_mask_max(high, ms_pivot_span).fillna(False)
    pl = _pivot_mask_min(low,  ms_pivot_span).fillna(False)

    piv_high = [(i, float(high.iat[i])) for i in range(len(d)) if bool(ph.iat[i])]
    piv_low  = [(i, float(low.iat[i]))  for i in range(len(d))  if bool(pl.iat[i])]

    highs2 = _last_two(piv_high)
    lows2  = _last_two(piv_low)

    label = ""
    trend = "RANGE"
    if len(highs2) == 2 and len(lows2) == 2:
        (_, h_prev), (_, h_last) = highs2[-2], highs2[-1]
        (_, l_prev), (_, l_last) = lows2[-2],  lows2[-1]
        hh_lh = "HH" if h_last > h_prev else "LH"
        hl_ll = "HL" if l_last > l_prev else "LL"
        label = f"{hh_lh}/{hl_ll}"
        if hh_lh == "HH" and hl_ll == "HL":
            trend = "UP"
        elif hh_lh == "LH" and hl_ll == "LL":
            trend = "DOWN"
        else:
            trend = "RANGE"

    d["ms_label"] = pd.Series([label]*len(d), index=d.index, dtype="object")
    d["ms_trend"] = pd.Series([trend]*len(d), index=d.index, dtype="object")
    return d



