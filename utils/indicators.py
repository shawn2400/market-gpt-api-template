# utils/indicators.py
from __future__ import annotations
import pandas as pd
import numpy as np

# -------------------------------------------------
# Helpers
# -------------------------------------------------
def _as_series(x: pd.Series) -> pd.Series:
    s = pd.to_numeric(pd.Series(x, copy=False), errors="coerce")
    return s.astype(float)

def _rma(series: pd.Series, period: int) -> pd.Series:
    """
    Wilder's RMA (EMA עם alpha=1/period), יציב יותר ל-RSI/ATR/ADX.
    """
    s = _as_series(series)
    alpha = 1.0 / float(period)
    r = pd.Series(index=s.index, dtype=float)
    if len(s) == 0:
        return r
    # ערך ראשון: ממוצע פשוט של period הראשון אם יש, אחרת הערך הראשון
    if len(s) >= period:
        r.iloc[0] = s.iloc[:period].mean()
    else:
        r.iloc[0] = s.iloc[0]
    for i in range(1, len(s)):
        prev = r.iloc[i - 1]
        curr = s.iloc[i]
        r.iloc[i] = prev * (1 - alpha) + alpha * curr
    return r

# -------------------------------------------------
# Indicators
# -------------------------------------------------
def ema(series: pd.Series, period: int) -> pd.Series:
    s = _as_series(series)
    return s.ewm(span=period, adjust=False).mean()

def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """
    RSI לפי Wilder:
    - מחשבים שינוי יומי
    - מפרקים ל-gain/loss
    - RMA ל-gain ול-loss
    - RSI = 100 - 100/(1+RS)
    """
    s = _as_series(series)
    if s.empty:
        return s.copy()

    delta = s.diff().fillna(0.0)
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)

    avg_gain = _rma(gain, period)
    avg_loss = _rma(loss, period)

    rs = pd.Series(np.where(avg_loss == 0.0, np.inf, avg_gain / avg_loss), index=s.index, dtype=float)
    out = 100.0 - (100.0 / (1.0 + rs))
    # נרמול לקצוות
    out = out.clip(lower=0.0, upper=100.0)
    return out

def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    ATR לפי Wilder: RMA של True Range.
    מצפה לעמודות: high, low, close
    """
    if df.empty:
        return pd.Series(dtype=float)
    high = _as_series(df["high"])
    low = _as_series(df["low"])
    close = _as_series(df["close"])

    prev_close = close.shift(1).fillna(close.iloc[0])
    tr = pd.concat([
        (high - low),
        (high - prev_close).abs(),
        (low - prev_close).abs()
    ], axis=1).max(axis=1)

    return _rma(tr, period)

def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    ADX קלאסי (Wilder):
    - מחשבים +DM ו- -DM
    - מחשבים TR ו-RMA(+DM), RMA(-DM), RMA(TR)
    - +DI/-DI = 100 * RMA(DM) / RMA(TR)
    - DX = 100 * |+DI - -DI| / (+DI + -DI)
    - ADX = RMA(DX)
    """
    if df.empty:
        return pd.Series(dtype=float)

    high = _as_series(df["high"])
    low = _as_series(df["low"])
    close = _as_series(df["close"])

    up_move = high.diff()
    down_move = (-low.diff())

    plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=high.index, dtype=float)
    minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=low.index, dtype=float)

    # TR ל-ATR
    prev_close = close.shift(1).fillna(close.iloc[0])
    tr = pd.concat([
        (high - low),
        (high - prev_close).abs(),
        (low - prev_close).abs()
    ], axis=1).max(axis=1)

    atr_rma = _rma(tr, period).replace(0.0, np.nan)
    plus_di = 100.0 * (_rma(plus_dm, period) / atr_rma)
    minus_di = 100.0 * (_rma(minus_dm, period) / atr_rma)

    di_sum = (plus_di + minus_di).replace(0.0, np.nan)
    dx = (np.abs(plus_di - minus_di) / di_sum) * 100.0

    adx_val = _rma(dx.fillna(0.0), period)
    return adx_val

def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    s = _as_series(series)
    ema_fast = ema(s, fast)
    ema_slow = ema(s, slow)
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist

def bollinger_bands(series: pd.Series, period: int = 20, std_factor: float = 2.0):
    s = _as_series(series)
    sma = s.rolling(period, min_periods=period).mean()
    std = s.rolling(period, min_periods=period).std()
    upper = sma + std_factor * std
    lower = sma - std_factor * std
    return sma, upper, lower

# -------------------------------------------------
# Orchestrator
# -------------------------------------------------
def prepare_indicators_for_backtest(df: pd.DataFrame) -> pd.DataFrame:
    """
    מצפה לעמודות: open, high, low, close, volume.
    מחזיר DataFrame עם עמודות אינדיקטורים סטנדרטיות.
    שמות עמודות מסונכרנים עם ה-API:
      - ema_21, ema_50 (לא 'ema21/ema50')
      - rsi, atr, adx
      - macd, macd_signal, macd_hist
      - bb_mid, bb_upper, bb_lower
    """
    if df is None or df.empty:
        return pd.DataFrame(columns=[
            "open","high","low","close","volume",
            "ema_21","ema_50","rsi","atr","adx",
            "macd","macd_signal","macd_hist",
            "bb_mid","bb_upper","bb_lower",
        ])

    # ודא טיפוסים תקינים
    base = df.copy()
    for col in ("open","high","low","close","volume"):
        if col in base.columns:
            base[col] = _as_series(base[col])
        else:
            base[col] = np.nan

    # EMA
    base["ema_21"] = ema(base["close"], 21)
    base["ema_50"] = ema(base["close"], 50)

    # RSI
    base["rsi"] = rsi(base["close"], 14)

    # ATR + ADX
    base["atr"] = atr(base, 14)
    base["adx"] = adx(base, 14)

    # MACD
    macd_line, signal_line, hist = macd(base["close"])
    base["macd"] = macd_line
    base["macd_signal"] = signal_line
    base["macd_hist"] = hist

    # Bollinger Bands
    mid, upper, lower = bollinger_bands(base["close"])
    base["bb_mid"] = mid
    base["bb_upper"] = upper
    base["bb_lower"] = lower

    return base




































