from __future__ import annotations
import os, ast
from typing import Dict, Any, Optional, List
import numpy as np
import pandas as pd
import httpx

# ===================== אינדיקטורים מהירים =====================
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
    out = 100.0 - (100.0 / (1.0 + rs))
    return out.clip(0.0, 100.0)

def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    if df is None or df.empty or period <= 0:
        return pd.Series(dtype=float)
    h = _to_float_series(df.get("high", np.nan))
    l = _to_float_series(df.get("low", np.nan))
    c = _to_float_series(df.get("close", np.nan))
    pc = c.shift(1)
    tr = pd.concat([(h - l), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    tr = tr.fillna((h - l))
    return _rma(tr, period)

def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    if df is None or df.empty or period <= 0:
        return pd.Series(dtype=float)
    h = _to_float_series(df.get("high", np.nan))
    l = _to_float_series(df.get("low", np.nan))
    c = _to_float_series(df.get("close", np.nan))
    up = h.diff(); down = -l.diff()
    plus_dm  = up.where((up > down) & (up > 0.0), 0.0).fillna(0.0)
    minus_dm = down.where((down > up) & (down > 0.0), 0.0).fillna(0.0)
    pc = c.shift(1)
    tr = pd.concat([(h - l), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    tr = tr.fillna((h - l))
    atr_r = _rma(tr, period).replace(0.0, np.nan)
    plus_di  = 100.0 * (_rma(plus_dm, period)  / atr_r)
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
    ef = ema(s, fast); es = ema(s, slow)
    line = ef - es
    sig  = ema(line, signal)
    hist = line - sig
    return line, sig, hist

def bollinger_bands(series: pd.Series, period: int = 20, std_factor: float = 2.0, ddof: int = 0):
    s = _to_float_series(series)
    if s.empty or period <= 0:
        empty = pd.Series(index=s.index, dtype=float)
        return empty, empty, empty
    sma = s.rolling(window=period, min_periods=period).mean()
    std = s.rolling(window=period, min_periods=period).std(ddof=ddof)
    return sma, sma + std_factor*std, sma - std_factor*std

def vwap(df: pd.DataFrame, period: Optional[int] = None) -> pd.Series:
    """
    Calculate Volume Weighted Average Price (VWAP)
    
    Args:
        df: DataFrame with 'high', 'low', 'close', 'volume' columns
        period: Rolling window period (None = cumulative from start)
    
    Returns:
        VWAP series
    """
    if df is None or df.empty:
        return pd.Series(dtype=float)
    
    h = _to_float_series(df.get("high", np.nan))
    l = _to_float_series(df.get("low", np.nan))
    c = _to_float_series(df.get("close", np.nan))
    v = _to_float_series(df.get("volume", np.nan))
    
    typical_price = (h + l + c) / 3.0
    pv = typical_price * v
    
    if period is None:
        return (pv.cumsum() / v.cumsum()).fillna(method='ffill')
    else:
        return (pv.rolling(window=period, min_periods=1).sum() / 
                v.rolling(window=period, min_periods=1).sum()).fillna(method='ffill')

def keltner_bands(df: pd.DataFrame, period: int = 20, atr_period: int = 14, multiplier: float = 2.0):
    """
    Calculate Keltner Bands (EMA-based volatility bands)
    
    Args:
        df: DataFrame with 'high', 'low', 'close' columns
        period: EMA period for basis line
        atr_period: ATR period for band width
        multiplier: ATR multiplier for bands
    
    Returns:
        Tuple of (basis, upper, lower) Series
    """
    if df is None or df.empty or period <= 0 or atr_period <= 0:
        empty = pd.Series(index=df.index if df is not None else [], dtype=float)
        return empty, empty, empty
    
    c = _to_float_series(df.get("close", np.nan))
    basis = ema(c, period)
    atr_val = atr(df, atr_period)
    
    upper = basis + (multiplier * atr_val)
    lower = basis - (multiplier * atr_val)
    
    return basis, upper, lower

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
    m, s, h = macd(base["close"], 12, 26, 9)
    base["macd"] = m; base["macd_signal"] = s; base["macd_hist"] = h
    mid, up, lo = bollinger_bands(base["close"], 20, 2.0, ddof=0)
    base["bb_mid"] = mid; base["bb_upper"] = up; base["bb_lower"] = lo
    for c in cols:
        if c not in base.columns: base[c] = np.nan
    return base[cols]

__all__ = [
    "ema","rsi","atr","adx","macd","bollinger_bands","vwap","keltner_bands","prepare_indicators_for_backtest"
]

# ===================== eval_regime – שפת כללים =====================
_BINANCE_HTTP = os.getenv("BINANCE_FAPI", "https://fapi.binance.com").rstrip("/")

_INTERVAL_MAP = {
    "1m":"1m","3m":"3m","5m":"5m","15m":"15m","30m":"30m",
    "1h":"1h","2h":"2h","4h":"4h","6h":"6h","8h":"8h","12h":"12h",
    "1d":"1d","3d":"3d","1w":"1w","1M":"1M"
}

def _norm_logic(expr: str) -> str:
    e = (expr or "")
    repl = {
        " AND ": " and ", " and ": " and ", "&": " and ",
        " OR ": " or ",  " or ": " or ",  "|": " or ",
        " NOT ": " not ", " not ": " not ", "!": " not ",
    }
    ee = " " + e + " "
    for k, v in repl.items(): ee = ee.replace(k, v)
    ee = ee.replace("AND", " and ").replace("OR", " or ").replace("NOT", " not ")
    return ee.strip()

_ALLOWED_NODES = (
    ast.Expression, ast.BoolOp, ast.UnaryOp, ast.BinOp,
    ast.And, ast.Or, ast.Not, ast.USub,
    ast.Compare, ast.Name, ast.Load, ast.Constant,
    ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Eq, ast.NotEq,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.Pow,
    ast.Call, ast.Tuple, ast.List
)

def _safe_eval_bool(expr: str, vars_map: Dict[str, float]) -> bool:
    """
    מפרש תנאי לוגי עם שמות משתנים מוגבלים:
    שמות מותרים: ema21, ema50, adx, atrpct, rsi, macd_hist
    דוגמאות:
        "ema21 >= ema50 and adx >= 20"
        "adx >= 22 and atrpct <= 0.015"
        "between(rsi,45,55) or abs(macd_hist) < 0.05"
    """
    expr = _norm_logic(expr)
    if not expr: return False

    # פונקציות עזר
    def between(x, lo, hi): return (x >= lo) and (x <= hi)
    allowed_names = {**vars_map, "between": between, "abs": abs}

    node = ast.parse(expr, mode="eval")
    for sub in ast.walk(node):
        if not isinstance(sub, _ALLOWED_NODES):
            raise ValueError(f"illegal token: {type(sub).__name__}")
        if isinstance(sub, ast.Name) and sub.id not in allowed_names:
            raise ValueError(f"unknown identifier: {sub.id}")
    val = eval(compile(node, "<expr>", "eval"), {"__builtins__": {}}, allowed_names)  # noqa: S307
    return bool(val)

async def eval_regime(symbol: str,
                      long_req: Optional[str] = None,
                      short_req: Optional[str] = None,
                      neutral_req: Optional[str] = None,
                      timeframe: str = "15m") -> Dict[str, Any]:
    """
    מחזיר {"want": "LONG"/"SHORT"/"NEUTRAL", "vars": {...}, "matched": "...", "tf": timeframe}
    כללי ברירת מחדל יילקחו מה-ENV:
      LONG_REQ, SHORT_REQ, NEUTRAL_REQ   (נפוץ: ema21>=ema50 / ema21<=ema50)
    נתונים זמינים בתוך הכלל:
      ema21, ema50, adx, atrpct, rsi, macd_hist
    """
    # === טעינת env ===
    long_req    = (long_req    or os.getenv("LONG_REQ")    or os.getenv("BTC_LONG_REQ")  or "ema21>=ema50")
    short_req   = (short_req   or os.getenv("SHORT_REQ")   or os.getenv("BTC_SHORT_REQ") or "ema21<=ema50")
    neutral_req = (neutral_req or os.getenv("NEUTRAL_REQ") or "")

    tf = _INTERVAL_MAP.get(timeframe, "15m")
    market_label = os.getenv("DEFAULT_MARKET", "futures").lower()

    url = f"{_BINANCE_HTTP}/fapi/v1/klines"
    params = {"symbol": symbol.upper(), "interval": tf, "limit": 200}
    async with httpx.AsyncClient(timeout=10.0) as cli:
        r = await cli.get(url, params=params)
        r.raise_for_status()
        kl = r.json()

    if not kl or len(kl) < 60:
        return {"want":"NEUTRAL","reason":"insufficient_data","tf":tf,"vars":{}}

    # בניית DF
    close = pd.Series([float(x[4]) for x in kl], dtype=float)
    high  = pd.Series([float(x[2]) for x in kl], dtype=float)
    low   = pd.Series([float(x[3]) for x in kl], dtype=float)
    df = pd.DataFrame({"close": close, "high": high, "low": low})

    # חישובים
    e21 = float(ema(close, 21).iloc[-1])
    e50 = float(ema(close, 50).iloc[-1])
    _adx = float(adx(pd.DataFrame({"high":high,"low":low,"close":close}), 14).iloc[-1])
    _atr = float(atr(pd.DataFrame({"high":high,"low":low,"close":close}), 14).iloc[-1])
    _rsi = float(rsi(close, 14).iloc[-1])
    _,_,_mh = macd(close, 12, 26, 9)
    _mhv = float(_mh.iloc[-1])
    last_close = float(close.iloc[-1])
    atrpct = (_atr / last_close) if last_close > 0 else float("nan")

    # דיווח מטריקה: ATR כיחס למחיר לפי סמל/טיים-פריים/שוק
    try:
        from utils.metrics_tracker import observe_atr_pct  # import מקומי כדי לא לשבור import-time
        if atrpct == atrpct and atrpct > 0.0:  # בדיקת NaN
            observe_atr_pct(symbol=symbol, atr_frac=float(atrpct),
                            timeframe=tf, market=market_label)
    except Exception:
        pass

    vars_map = {
        "ema21": e21,
        "ema50": e50,
        "adx": _adx,
        "atrpct": atrpct,  # יחס ATR למחיר (למשל <= 0.015)
        "rsi": _rsi,
        "macd_hist": _mhv,
    }

    # ADX/ATR% “שער” מה-ENV (אופציונלי) + תמיכה פר-טייםפריים
    tf_key = tf.lower()
    adx_tf_override = os.getenv(f"REGIME_ADX_MIN_{tf_key}", None)
    if adx_tf_override not in (None, ""):
        adx_min = float(adx_tf_override)
    else:
        adx_min = float(os.getenv("REGIME_ADX_MIN", os.getenv("ADX_MIN","0") or 0) or 0)

    atrpct_max = float(os.getenv("REGIME_ATRPCT_MAX", os.getenv("AUTO_TRAIL_ATRPCT_MAX","10") or 10) or 10)

    gated_out = False
    gate_reason: List[str] = []
    # שערים חלים על LONG/SHORT בלבד (NEUTRAL נבדק תמיד)
    if adx_min > 0 and not (_adx >= adx_min):
        gate_reason.append(f"adx<{adx_min}")
    if atrpct_max < 10 and not (atrpct <= atrpct_max):
        gate_reason.append(f"atrpct>{atrpct_max}")
    gated_out = bool(gate_reason)

    # התאמת כללים
    want = "NEUTRAL"; matched = None
    try:
        if long_req and _safe_eval_bool(long_req, vars_map) and not gated_out:
            want, matched = "LONG", long_req
        elif short_req and _safe_eval_bool(short_req, vars_map) and not gated_out:
            want, matched = "SHORT", short_req
        elif neutral_req and _safe_eval_bool(neutral_req, vars_map):
            want, matched = "NEUTRAL", neutral_req
        else:
            want = "NEUTRAL"
    except Exception as e:
        return {"want":"NEUTRAL","error":f"rule_parse:{e}","tf":tf,"vars":vars_map}

    return {
        "want": want,
        "tf": tf,
        "vars": vars_map,
        "matched": matched,
        **({"gated_by": gate_reason} if gate_reason else {})
    }









