# -*- coding: utf-8 -*-
from __future__ import annotations
"""
אינדיקטורים משלימים מהירים (לשילוב אופציונלי בסריקה/תצוגה).
כל הפונקציות מחזירות dict עם: series / signals / context.
"""

from typing import Dict, Any, List, Optional
import pandas as pd  # type: ignore
import numpy as np   # type: ignore


def squeeze_bb_kc(
    df: pd.DataFrame,
    bb_len: int = 20,
    bb_mult: float = 2.0,
    kc_len: int = 20,
    kc_mult: float = 1.5,
) -> Dict[str, Any]:
    c = df["close"].astype(float)
    ma = c.rolling(bb_len).mean()
    sd = c.rolling(bb_len).std(ddof=0)
    bb_up, bb_dn = ma + bb_mult * sd, ma - bb_mult * sd

    # TR מקורב (אין כאן high/low חובה — אם חסר נשען על close-diff)
    if "high" in df.columns and "low" in df.columns:
        tr = (df["high"].astype(float) - df["low"].astype(float)).ewm(alpha=1 / kc_len, adjust=False).mean()
    else:
        tr = c.diff().abs().ewm(alpha=1 / kc_len, adjust=False).mean()

    kc_up, kc_dn = ma + kc_mult * tr, ma - kc_mult * tr
    in_sq = (bb_up < kc_up) & (bb_dn > kc_dn)
    release = in_sq.shift(1).fillna(False) & (~in_sq)

    signals: List[Dict[str, Any]] = []
    if len(df) > 0 and bool(release.iloc[-1]):
        ts = df.index[-1] if df.index.is_monotonic_increasing else None
        signals.append({"ts": ts, "side": "long", "strength": 8.0, "reason": {"squeeze": "release"}})

    return {
        "series": {"bb_up": bb_up, "bb_dn": bb_dn, "kc_up": kc_up, "kc_dn": kc_dn},
        "signals": signals,
        "context": {},
    }


def donchian(df: pd.DataFrame, length: int = 20) -> Dict[str, Any]:
    h = df["high"].astype(float) if "high" in df.columns else df["close"].astype(float)
    l = df["low"].astype(float) if "low" in df.columns else df["close"].astype(float)
    c = df["close"].astype(float)

    up = h.rolling(length).max()
    dn = l.rolling(length).min()

    sig: List[Dict[str, Any]] = []
    if len(df) > 1:
        prev_up = up.shift(1).iloc[-1]
        prev_dn = dn.shift(1).iloc[-1]
        last_c = c.iloc[-1]
        ts = df.index[-1] if df.index.is_monotonic_increasing else None
        if np.isfinite(prev_up) and last_c > prev_up:
            sig.append({"ts": ts, "side": "long", "strength": 8.0, "reason": {"donchian": "breakout"}})
        if np.isfinite(prev_dn) and last_c < prev_dn:
            sig.append({"ts": ts, "side": "short", "strength": 8.0, "reason": {"donchian": "breakdown"}})

    return {"series": {"upper": up, "lower": dn}, "signals": sig, "context": {}}


def avwap(df: pd.DataFrame, anchor: Optional[str] = None) -> Dict[str, Any]:
    tp = (df["high"].astype(float) + df["low"].astype(float) + df["close"].astype(float)) / 3.0
    v = df["volume"].replace(0, np.nan).astype(float)
    vwap = (tp * v).cumsum() / v.cumsum()
    return {"series": {"avwap": vwap}, "signals": [], "context": {"anchor": anchor}}


def chandelier(df: pd.DataFrame, atr_len: int = 22, mult: float = 3.0) -> Dict[str, Any]:
    h = df["high"].astype(float) if "high" in df.columns else df["close"].astype(float)
    l = df["low"].astype(float) if "low" in df.columns else df["close"].astype(float)

    # True Range מקורב
    tr = (h - l).ewm(alpha=1 / atr_len, adjust=False).mean()
    ce_long = h.rolling(1).max() - mult * tr
    ce_short = l.rolling(1).min() + mult * tr
    return {"series": {"ce_long": ce_long, "ce_short": ce_short}, "signals": [], "context": {}}


def vol_regime(df: pd.DataFrame, look: int = 100) -> Dict[str, Any]:
    c = df["close"].astype(float)
    ret = c.pct_change().abs()
    # ספים אמפיריים לישורת / תנודתיות
    if len(ret) < look + 10:
        return {"series": {"state": ret}, "signals": [], "context": {"regime": "med"}}
    p = ret.rolling(look).quantile([0.33, 0.66]).unstack()
    lo, hi = p[0.33], p[0.66]
    state = ret.rolling(10).mean()
    thresh_lo, thresh_hi = lo.iloc[-1], hi.iloc[-1]
    last_state = state.iloc[-1]
    if not np.isfinite(last_state):
        regime = "med"
    else:
        regime = "low" if last_state <= thresh_lo else ("high" if last_state >= thresh_hi else "med")
    return {"series": {"state": state}, "signals": [], "context": {"regime": regime}}


__all__ = ["squeeze_bb_kc", "donchian", "avwap", "chandelier", "vol_regime"]

