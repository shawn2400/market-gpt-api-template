# -*- coding: utf-8 -*-
from __future__ import annotations

import pandas as pd
import numpy as np
from typing import Optional

# ננסה להשתמש בפונקציה קיימת (אם קיימת בפרויקט)
try:
    from utils.indicators import adx as _adx_external  # type: ignore
except Exception:
    _adx_external = None  # fallback פנימי אם לא קיים מודול/פונקציה


def _rma(series: pd.Series, period: int) -> pd.Series:
    """
    Wilder's RMA (a.k.a. SMMA) — כמו EMA עם alpha = 1/period אך עם seed שונה.
    ממומש בצורה יציבה: seed ממוצע ראשוני, ואז נוסחת RMA איטרטיבית.
    """
    s = pd.Series(series, dtype="float64").copy()
    if s.empty or period <= 0:
        return s * np.nan
    # seed: ממוצע פשוט של period הדגימות הראשונות (אם קיימות)
    if len(s) < period:
        # לא מספיק דגימות: נחזיר NaN
        return pd.Series(np.nan, index=s.index)
    seed = s.iloc[:period].mean()
    out = np.empty(len(s), dtype="float64")
    out[:] = np.nan
    out[period - 1] = seed
    alpha = 1.0 / float(period)
    for i in range(period, len(s)):
        out[i] = out[i - 1] + alpha * (s.iloc[i] - out[i - 1])
    return pd.Series(out, index=s.index)


def _adx_fallback(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    חישוב ADX קלאסי על בסיס עמודות: high, low, close.
    אם חסר מידע נדרש או אין מספיק שורות – יוחזר NaN.
    """
    cols = {"high", "low", "close"}
    if df is None or df.empty or not cols.issubset(set(df.columns)):
        return pd.Series(np.nan, index=(df.index if isinstance(df, pd.DataFrame) else pd.RangeIndex(0)))

    high = pd.to_numeric(df["high"], errors="coerce")
    low = pd.to_numeric(df["low"], errors="coerce")
    close = pd.to_numeric(df["close"], errors="coerce")

    # הפרשים
    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=df.index)

    tr1 = (high - low).abs()
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    # החלקה בסגנון ווילדר
    atr = _rma(tr, period)
    plus_di = 100.0 * _rma(plus_dm, period) / atr
    minus_di = 100.0 * _rma(minus_dm, period) / atr

    dx = (100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di)).replace([np.inf, -np.inf], np.nan)
    adx = _rma(dx, period)

    return adx


def _compute_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    מנסה קודם ADX חיצוני (אם קיים בפרויקט), אחרת נופל לפונקציית fallback פנימית.
    """
    if df is None or df.empty:
        return pd.Series(np.nan, index=(df.index if isinstance(df, pd.DataFrame) else pd.RangeIndex(0)))
    # אם כבר יש עמודת adx — נחזיר אותה
    if "adx" in df.columns:
        return pd.to_numeric(df["adx"], errors="coerce")

    # ניסיון שימוש בפונקציה החיצונית של הפרויקט (אם קיימת)
    if _adx_external is not None:
        try:
            adx_ser = _adx_external(df)  # מצופה להחזיר pd.Series מיושר לאינדקס של df
            adx_ser = pd.to_numeric(adx_ser, errors="coerce")
            # ודא התאמה לאינדקס
            return adx_ser.reindex(df.index)
        except Exception:
            # ניפול לפולבק פנימי אם החישוב החיצוני נכשל
            pass

    # חישוב ADX פנימי
    return _adx_fallback(df, period=period)


def detect_chop_zones(df: pd.DataFrame, adx_thresh: float = 18.0, period: int = 14, min_len: int = 20) -> pd.DataFrame:
    """
    מסמן אזורי דשדוש (CHOP) לפי ADX נמוך.
    - אם יש df["adx"], נשתמש בה.
    - אחרת נחשב ADX (חיצוני אם קיים; אחרת fallback פנימי).
    - אם חסרות עמודות חובה (high/low/close) ולא ניתן ADX — נסמן chop=False בלי לשבור.

    פרמטרים:
    adx_thresh : סף ADX שמתחתיו נחשב "דשדוש"
    period     : פרק זמן ל־ADX (Wilder)
    min_len    : מינימום שורות לפני חישוב; אם פחות — נחזיר adx=NaN ו־chop=False
    """
    if df is None or df.empty:
        return df

    out = df.copy()

    # הבטחת סוגים מספריים לעמודות עיקריות (אם קיימות)
    for c in ("open", "high", "low", "close", "volume"):
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce")

    if len(out) < max(min_len, period + 5):
        # מעט מדי דגימות — לא נחשב ADX
        if "adx" not in out.columns:
            out["adx"] = np.nan
        out["chop"] = False
        return out

    adx_ser = _compute_adx(out, period=period)
    out["adx"] = adx_ser  # יחליף אם כבר קיים

    # סימון CHOP
    try:
        out["chop"] = (out["adx"] < float(adx_thresh)).fillna(False)
    except Exception:
        out["chop"] = False

    return out



