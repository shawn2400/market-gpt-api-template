from __future__ import annotations
import pandas as pd

try:
    from utils.indicators import adx as _adx_fn  # type: ignore
except Exception:
    _adx_fn = None  # fallback

def _compute_adx_if_missing(df: pd.DataFrame) -> pd.DataFrame:
    if "adx" in df.columns:
        return df
    if _adx_fn is None:
        # בלי ADX – נסמן chop=False לכולם (לא נשבר)
        df = df.copy()
        df["adx"] = float("nan")
        return df
    try:
        adx_ser = _adx_fn(df)
        df = df.copy()
        df["adx"] = adx_ser.reindex(df.index)
    except Exception:
        df = df.copy()
        df["adx"] = float("nan")
    return df

def detect_chop_zones(df: pd.DataFrame, adx_thresh: float = 18.0) -> pd.DataFrame:
    """
    מסמן אזורי דשדוש לפי ADX נמוך. אם ADX חסר – נחשב אותו (אם ניתן).
    """
    if df is None or df.empty:
        return df
    df = _compute_adx_if_missing(df)
    df = df.copy()
    try:
        df["chop"] = (df["adx"] < float(adx_thresh)).fillna(False)
    except Exception:
        df["chop"] = False
    return df

