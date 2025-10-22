# utils/indicators.py
from __future__ import annotations
import pandas as pd
import numpy as np
from typing import Dict, Any, List, Optional
import httpx
import os

# ========= אינדיקטורים (כמו אצלך) =========
def _to_float_series(x: pd.Series) -> pd.Series:
    if isinstance(x, pd.Series):
        s = pd.to_numeric(x, errors="coerce")
        return s.astype(float)
    s = pd.Series(x, copy=False)
    s = pd.to_numeric(s, errors="coerce")
    return s.astype(float)

def _rma(series: pd.Series, period: int) -> pd.Series:
    s = _to_float_series(series)
    if period <= 0 or s.empty:
        return pd.Series(index=s.index, dtype=float)
    alpha = 1.0 / float(period)
    return s.ewm(alpha=alpha, adjust=False).mean()

def ema(series: pd.Series, period: int) -> pd.Series:
    s = _to_float_series(series)
    if period <= 0 or s.empty:
        return pd.Series(index=s.index, dtype=float)
    return s.ewm(span=period, adjust=False).mean()

def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    s = _to_float_series(series)
    if s.empty or period <= 0:
        return pd.Series(index=s.index, dtype=float)
    delta = s.diff()
    gain = delta.clip(lower=0.0).fillna(0.0)
    loss = (-delta).clip(lower=0.0).fillna(0.0)
    avg_gain = _rma(gain, period)
    avg_loss = _rma(loss, period)
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = avg_gain / avg_loss.replace(0.0, np.nan)
    rs = rs.replace([np.inf, -np.inf], np.nan).fillna(np.inf)
    rsi_val = 100.0 - (100.0 / (1.0 + rs))
    return rsi_val.clip(0.0, 100.0)

def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    if df is None or df.empty or period <= 0:
        return pd.Series(dtype=float)
    h = _to_float_series(df.get("high", np.nan))
    l = _to_float_series(df.get("low", np.nan))
    c = _to_float_series(df.get("close", np.nan))
    prev_c = c.shift(1)
    tr = pd.concat([(h - l), (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
    tr = tr.fillna((h - l))
    return _rma(tr, period)

def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    if df is None or df.empty or period <= 0:
        return pd.Series(dtype=float)
    h = _to_float_series(df.get("high", np.nan))
    l = _to_float_series(df.get("low", np.nan))
    c = _to_float_series(df.get("close", np.nan))
    up_move = h.diff()
    down_move = -l.diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0.0), 0.0).fillna(0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0.0), 0.0).fillna(0.0)
    prev_c = c.shift(1)
    tr = pd.concat([(h - l), (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
    tr = tr.fillna((h - l))
    atr_r = _rma(tr, period).replace(0.0, np.nan)
    plus_di = 100.0 * (_rma(plus_dm, period) / atr_r)
    minus_di = 100.0 * (_rma(minus_dm, period) / atr_r)
    denom = (plus_di + minus_di).replace(0.0, np.nan)
    dx = (np.abs(plus_di - minus_di) / denom) * 100.0
    dx = dx.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return _rma(dx, period)

def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    s = _to_float_series(series)
    if s.empty:
        empty = pd.Series(index=s.index, dtype=float)
        return empty, empty, empty
    ema_fast = ema(s, fast)
    ema_slow = ema(s, slow)
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist

def bollinger_bands(series: pd.Series, period: int = 20, std_factor: float = 2.0, ddof: int = 0):
    s = _to_float_series(series)
    if s.empty or period <= 0:
        empty = pd.Series(index=s.index, dtype=float)
        return empty, empty, empty
    sma = s.rolling(window=period, min_periods=period).mean()
    std = s.rolling(window=period, min_periods=period).std(ddof=ddof)
    upper = sma + std_factor * std
    lower = sma - std_factor * std
    return sma, upper, lower

def prepare_indicators_for_backtest(df: pd.DataFrame) -> pd.DataFrame:
    cols = ["open","high","low","close","volume",
            "ema_21","ema_50","rsi","atr","adx",
            "macd","macd_signal","macd_hist",
            "bb_mid","bb_upper","bb_lower"]
    if df is None or df.empty:
        return pd.DataFrame(columns=cols)
    base = df.copy()
    for c in ("open","high","low","close","volume"):
        base[c] = _to_float_series(base.get(c, np.nan))
    base["ema_21"] = ema(base["close"], 21)
    base["ema_50"] = ema(base["close"], 50)
    base["rsi"]    = rsi(base["close"], 14)
    base["atr"]    = atr(base, 14)
    base["adx"]    = adx(base, 14)
    macd_line, macd_sig, macd_hist = macd(base["close"], 12, 26, 9)
    base["macd"] = macd_line
    base["macd_signal"] = macd_sig
    base["macd_hist"] = macd_hist
    bb_mid, bb_up, bb_low = bollinger_bands(base["close"], 20, 2.0, ddof=0)
    base["bb_mid"] = bb_mid
    base["bb_upper"] = bb_up
    base["bb_lower"] = bb_low
    for c in cols:
        if c not in base.columns:
            base[c] = np.nan
    return base[cols]

__all__ = [
    "ema","rsi","atr","adx","macd","bollinger_bands","prepare_indicators_for_backtest"
]

# ========= eval_regime (חדש) =========
_BINANCE_HTTP = os.getenv("BINANCE_FAPI", "https://fapi.binance.com").rstrip("/")

_INTERVAL_MAP = {
    "1m":"1m","3m":"3m","5m":"5m","15m":"15m","30m":"30m",
    "1h":"1h","2h":"2h","4h":"4h","6h":"6h","8h":"8h","12h":"12h",
    "1d":"1d","3d":"3d","1w":"1w","1M":"1M"
}

def _parse_req(expr: str, ema21: float, ema50: float) -> bool:
    expr = (expr or "").replace(" ", "").lower()
    if not expr:
        return False
    # תומך רק בהשוואות EMA בסיסיות:
    # ema21>=ema50  |  ema21>ema50  |  ema21<=ema50  |  ema21<ema50  |  ema21==ema50
    left, op, right = "ema21", None, "ema50"
    if ">=" in expr: op = ">="; parts = expr.split(">=")
    elif "<=" in expr: op = "<="; parts = expr.split("<=")
    elif "==" in expr: op = "=="; parts = expr.split("==")
    elif ">" in expr:  op = ">";  parts = expr.split(">")
    elif "<" in expr:  op = "<";  parts = expr.split("<")
    else:
        return False
    if len(parts) != 2: return False
    l = parts[0].strip()
    r = parts[1].strip()
    def val(x: str) -> float:
        if x == "ema21": return float(ema21)
        if x == "ema50": return float(ema50)
        try: return float(x)
        except: return float("nan")
    lv = val(l); rv = val(r)
    if op == ">=": return lv >= rv
    if op == "<=": return lv <= rv
    if op == ">":  return lv > rv
    if op == "<":  return lv < rv
    if op == "==": return lv == rv
    return False

async def eval_regime(symbol: str, long_req: str = "ema21>=ema50", short_req: str = "ema21<=ema50", timeframe: str = "15m") -> Dict[str, Any]:
    """
    מחזיר {"want": "LONG"/"SHORT"/"NEUTRAL", "ema21": ..., "ema50": ..., "tf": timeframe}
    מושך klines ציבורי מ-Binance Futures (לא דורש API key).
    """
    tf = _INTERVAL_MAP.get(timeframe, "15m")
    url = f"{_BINANCE_HTTP}/fapi/v1/klines"
    params = {"symbol": symbol.upper(), "interval": tf, "limit": 120}
    async with httpx.AsyncClient(timeout=10.0) as cli:
        r = await cli.get(url, params=params)
        r.raise_for_status()
        kl = r.json()  # [ [openTime,open,high,low,close,volume,...], ... ]
    if not kl or len(kl) < 60:
        return {"want":"NEUTRAL","tf":tf,"reason":"insufficient_data"}
    closes = pd.Series([float(x[4]) for x in kl], dtype=float)
    e21 = ema(closes, 21).iloc[-1]
    e50 = ema(closes, 50).iloc[-1]
    want = "NEUTRAL"
    if _parse_req(long_req, e21, e50):
        want = "LONG"
    elif _parse_req(short_req, e21, e50):
        want = "SHORT"
    return {"want": want, "ema21": float(e21), "ema50": float(e50), "tf": tf}
















