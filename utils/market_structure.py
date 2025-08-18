from __future__ import annotations
from typing import List, Tuple
import pandas as pd
import numpy as np

def _last_two(arr: List[Tuple[int, float]]) -> List[Tuple[int, float]]:
    return arr[-2:] if len(arr) >= 2 else arr

def add_market_structure_columns(
    df: pd.DataFrame,
    *,
    ms_lookback: int = 5,          # לא משמש כאן, אבל נשמר לחתימה תואמת
    ms_pivot_span: int = 3,
    high_col: str = "high",
    low_col: str = "low",
) -> pd.DataFrame:
    """
    מוסיף שתי עמודות:
      - ms_label:  'HH/HL' , 'LH/LL' , 'HH/LL' , 'LH/HL' (השוואת שני שיאים ושני שפלים אחרונים)
      - ms_trend:  'UP' / 'DOWN' / 'RANGE'
    """
    d = df.copy()
    for c in (high_col, low_col):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d = d.dropna(subset=[high_col, low_col]).copy()

    label = ""
    trend = "RANGE"

    if len(d) >= (ms_pivot_span * 2 + 1):
        # פיבוטים בקירוב: מקס/מינ מרכזי
        roll_max = d[high_col].rolling(ms_pivot_span, center=True, min_periods=1).max()
        roll_min = d[low_col].rolling(ms_pivot_span, center=True, min_periods=1).min()
        mask_h = (d[high_col] == roll_max)
        mask_l = (d[low_col] == roll_min)

        pivH: List[Tuple[int, float]] = [(i, float(d[high_col].iat[i])) for i, v in enumerate(mask_h) if bool(v)]
        pivL: List[Tuple[int, float]] = [(i, float(d[low_col].iat[i]))  for i, v in enumerate(mask_l) if bool(v)]

        highs2 = _last_two(pivH)
        lows2  = _last_two(pivL)

        if len(highs2) == 2 and len(lows2) == 2:
            hh_lh = "HH" if highs2[-1][1] > highs2[-2][1] else "LH"
            hl_ll = "HL" if lows2[-1][1]  > lows2[-2][1]  else "LL"
            label = f"{hh_lh}/{hl_ll}"
            if hh_lh == "HH" and hl_ll == "HL":
                trend = "UP"
            elif hh_lh == "LH" and hl_ll == "LL":
                trend = "DOWN"
            else:
                trend = "RANGE"

    # נשכפל את הערכים האחרונים על כל השורות (הסורק משתמש בשורה האחרונה)
    d["ms_label"] = pd.Series([label] * len(d), index=d.index, dtype="object")
    d["ms_trend"] = pd.Series([trend] * len(d), index=d.index, dtype="object")
    return d



