# utils/indicators.py
from __future__ import annotations
import pandas as pd
import numpy as np
from typing import Dict, Any, List, Optional
import os, math, datetime as _dt

# ====== הקוד שלך נשאר (ema/rsi/atr/adx/macd/bollinger/prepare_indicators_for_backtest) ======
# ... (השאר כמו אצלך) ...

# --- BEGIN: תוכן המקורי שלך (מקוצר כאן לצורך הדוגמא) ---
def _to_float_series(x: pd.Series) -> pd.Series:
    if isinstance(x, pd.Series):
        s = pd.to_numeric(x, errors="coerce")
        return s.astype(float)
    s = pd.Series(x, copy=False)
    s = pd.to_numeric(s, errors="coerce")
    return s.astype(float)

def _rma(series: pd.Series, period: int) -> pd.Series:
    if period <= 0 or series is None or series.empty:
        return pd.Series(dtype=float)
    alpha = 1.0 / float(period)
    return _to_float_series(series).ewm(alpha=alpha, adjust=False).mean()

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
    cols = ["open","high","low","close","volume","ema_21","ema_50","rsi","atr","adx","macd","macd_signal","macd_hist","bb_mid","bb_upper","bb_lower"]
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
# --- END: תוכן המקורי שלך ---

# ===== Regime evaluator (ASYNC) =====
import httpx

_BINANCE_HTTP = os.getenv("BINANCE_FUTURES_HTTP_BASE", os.getenv("BINANCE_FAPI", "https://fapi.binance.com")).rstrip("/")

_tf_map = {
    "1m":"1m","3m":"3m","5m":"5m","15m":"15m","30m":"30m",
    "1h":"1h","2h":"2h","4h":"4h","6h":"6h","8h":"8h","12h":"12h",
    "1d":"1d","3d":"3d","1w":"1w","1M":"1M"
}

async def _fetch_klines(symbol: str, interval: str, limit: int = 200) -> pd.DataFrame:
    iv = _tf_map.get(interval, "15m")
    url = f"{_BINANCE_HTTP}/fapi/v1/klines"
    params = {"symbol": symbol.upper(), "interval": iv, "limit": int(limit)}
    async with httpx.AsyncClient(timeout=15.0) as cli:
        r = await cli.get(url, params=params)
        r.raise_for_status()
        data = r.json()
    # columns: open time, o,h,l,c, v, close time, ...
    arr = []
    for k in data:
        arr.append({
            "t": int(k[0]),
            "open": float(k[1]), "high": float(k[2]), "low": float(k[3]), "close": float(k[4]), "volume": float(k[5])
        })
    df = pd.DataFrame(arr)
    return df

def _expr_bool(expr: str, ema21: float, ema50: float) -> bool:
    """
    תומך בביטויים פשוטים כמו:
      "ema21>=ema50", "ema21>ema50", "ema21<=ema50", "ema21<ema50"
    """
    e = (expr or "").replace(" ", "").lower()
    if not e:
        return False
    if ">=" in e:
        l, r = e.split(">=")
        return (l=="ema21" and r=="ema50" and ema21 >= ema50)
    if "<=" in e:
        l, r = e.split("<=")
        return (l=="ema21" and r=="ema50" and ema21 <= ema50)
    if ">" in e:
        l, r = e.split(">")
        return (l=="ema21" and r=="ema50" and ema21 > ema50)
    if "<" in e:
        l, r = e.split("<")
        return (l=="ema21" and r=="ema50" and ema21 < ema50)
    return False

async def eval_regime(symbol: str, long_req: str = "ema21>=ema50", short_req: str = "ema21<=ema50", timeframe: str = "15m") -> Dict[str, Any]:
    """
    מחזיר {"want": "LONG"/"SHORT"/"NEUTRAL", "ema21":..., "ema50":...}
    """
    df = await _fetch_klines(symbol, timeframe, limit=120)
    if df.empty:
        return {"want": "NEUTRAL"}
    # EMA על close
    df["ema21"] = ema(df["close"], 21)
    df["ema50"] = ema(df["close"], 50)
    ema21_v = float(df["ema21"].iloc[-1])
    ema50_v = float(df["ema50"].iloc[-1])
    want = "NEUTRAL"
    is_long  = _expr_bool(long_req, ema21_v, ema50_v)
    is_short = _expr_bool(short_req, ema21_v, ema50_v)
    if is_long and not is_short:
        want = "LONG"
    elif is_short and not is_long:
        want = "SHORT"
    return {"want": want, "ema21": ema21_v, "ema50": ema50_v, "timeframe": timeframe}








































