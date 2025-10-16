# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Optional, List, Tuple
import os
import math

import pandas as pd  # type: ignore


def _safe_float(x) -> float:
    try:
        return float(x)
    except Exception:
        return math.nan


def compute_vwap(df: pd.DataFrame) -> float:
    """
    מצפה לעמודות: high, low, close, volume.
    """
    if df is None or df.empty:
        return float("nan")
    tp = (df["high"].astype(float) + df["low"].astype(float) + df["close"].astype(float)) / 3.0
    vol = pd.to_numeric(df["volume"], errors="coerce")
    vol_sum = float(vol.sum())
    denom = vol_sum if vol_sum != 0.0 else 1e-12
    vwap = (tp * vol).sum() / denom
    return float(vwap)


def compute_obv(df: pd.DataFrame) -> float:
    """
    On-Balance Volume בסיסי על close/volume.
    """
    if df is None or df.empty:
        return 0.0
    close = pd.to_numeric(df["close"], errors="coerce").to_numpy(dtype=float, copy=False)
    vol = pd.to_numeric(df["volume"], errors="coerce").to_numpy(dtype=float, copy=False)
    obv = 0.0
    for i in range(1, len(close)):
        if close[i] > close[i - 1]:
            obv += vol[i]
        elif close[i] < close[i - 1]:
            obv -= vol[i]
    return float(obv)


def compute_cvd_from_trades_dev(symbol: str, limit: int = 1000) -> Optional[float]:
    """
    Dev-only: CVD מאגרגציות־טריידים של Binance (חסום כברירת־מחדל).
    דורש ALLOW_HTTP_IN_INDICATORS=1. לא לשימוש בפרודקשן חם.
    """
    if os.getenv("ALLOW_HTTP_IN_INDICATORS", "0") != "1":
        return None

    import httpx  # type: ignore
    base = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com").rstrip("/")
    symbol = symbol.upper().strip()

    with httpx.Client(timeout=6.0) as c:
        r = c.get(f"{base}/fapi/v1/aggTrades", params={"symbol": symbol, "limit": max(1, min(1000, limit))})
        r.raise_for_status()
        trades = r.json()

    cvd = 0.0
    for t in trades:
        q = _safe_float(t.get("q"))
        # maker=true => מכירה (לחץ שלילי), אחרת קנייה
        cvd += (-q if t.get("m") else q)
    return float(cvd)


# ────────────────────────────────────────────────────────────────────────────
# Advanced (ל־pretrade_checklist)
# ────────────────────────────────────────────────────────────────────────────
def _ema(series: List[float], period: int) -> List[float]:
    if not series or period <= 1:
        return series[:]
    k = 2.0 / (period + 1.0)
    out: List[float] = []
    ema_val = series[0]
    out.append(ema_val)
    for i in range(1, len(series)):
        ema_val = series[i] * k + ema_val * (1 - k)
        out.append(ema_val)
    return out


def detect_regime(adx: float, atr_pct: float, *, adx_trend: float = 22.0, chop_atr_pct: float = 0.6) -> int:
    """
    0=Mean-Revert, 1=Choppy, 2=Trending
    atr_pct צפוי באחוזים (למשל 0.8 -> 0.8%)
    """
    try:
        a = float(adx)
        atrp = float(atr_pct)
        if a >= adx_trend and atrp >= chop_atr_pct:
            return 2
        if atrp < chop_atr_pct:
            return 1
        return 0
    except Exception:
        return 1


def compression_bandwidth(closes: List[float], period: int = 20) -> float:
    """
    רוחב דחיסה (סטיית תקן יחסית ממוצע) באחוזים – פשוט וזריז.
    """
    if not closes or len(closes) < max(5, period):
        return 999.0
    win = closes[-period:]
    mu = sum(win) / float(len(win))
    if mu <= 0:
        return 999.0
    var = sum((x - mu) ** 2 for x in win) / float(len(win))
    sd = math.sqrt(max(0.0, var))
    bw = (sd / mu) * 100.0
    return float(bw)


def trend_confidence(closes: List[float], adx: float, *, ema_fast: int = 21, ema_slow: int = 50) -> float:
    """
    0..1 – שילוב כיוון EMA ו-ADX.
    """
    if not closes or len(closes) < max(ema_fast, ema_slow):
        return 0.5
    ef = _ema(closes, ema_fast)
    es = _ema(closes, ema_slow)
    up = 1.0 if ef[-1] >= es[-1] else 0.0
    adx_norm = max(0.0, min(1.0, float(adx) / 40.0))
    return float(0.6 * up + 0.4 * adx_norm)


def _rsi_from_ohlcv(kl: List[List[float]], length: int) -> float:
    if not kl or len(kl) < length + 1:
        return 50.0
    closes = [float(r[4]) for r in kl]
    gains, losses = 0.0, 0.0
    for i in range(1, length + 1):
        ch = closes[-i] - closes[-i - 1]
        if ch >= 0:
            gains += ch
        else:
            losses -= ch
    if losses == 0:
        return 70.0
    rs = (gains / float(length)) / (losses / float(length))
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return float(max(0.0, min(100.0, rsi)))


def rsi_composite(kl: List[List[float]], len_ltf: int = 14, len_htf: int = 28) -> float:
    """
    ממוצע RSI משתי סקיילות – רזה, 0..100.
    """
    r1 = _rsi_from_ohlcv(kl, len_ltf)
    r2 = _rsi_from_ohlcv(kl, len_htf)
    return float((r1 + r2) / 2.0)


def ema_gap_guard(closes: List[float], period: int = 21, max_gap_pct: float = 6.0) -> Tuple[bool, float]:
    """
    בודק מרחק מה-EMA(period) באחוזים.
    מחזיר (ok, gap_pct).
    """
    if not closes or len(closes) < period:
        return True, 0.0
    ema_vals = _ema(closes, period)
    last = closes[-1]
    ema_last = ema_vals[-1]
    gap_pct = abs((last - ema_last) / max(1e-12, ema_last)) * 100.0
    return (gap_pct <= max_gap_pct, float(gap_pct))


__all__ = [
    "compute_vwap",
    "compute_obv",
    "compute_cvd_from_trades_dev",
    "detect_regime",
    "compression_bandwidth",
    "trend_confidence",
    "rsi_composite",
    "ema_gap_guard",
]





