# utils/analyze.py
import os
import requests
import pandas as pd
from typing import Dict, Any
from utils.indicators import prepare_indicators_for_backtest

FUTURES_BASE = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com")

def _fetch_klines(symbol: str, interval: str = "15m", limit: int = 200) -> pd.DataFrame:
    url = f"{FUTURES_BASE}/fapi/v1/klines"
    r = requests.get(url, params={"symbol": symbol, "interval": interval, "limit": limit}, timeout=10)
    r.raise_for_status()
    arr = r.json()
    if not arr:
        return pd.DataFrame()
    cols = [
        "open_time","open","high","low","close","volume","close_time",
        "qv","nTrades","taker_base","taker_quote","x"
    ]
    df = pd.DataFrame(arr, columns=cols[:len(arr[0])])
    for c in ("open","high","low","close","volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df[["open","high","low","close","volume"]]

def _generate_signal(row: Dict[str, Any]) -> Dict[str, Any]:
    """
    מחזיר אות החלטה (LONG/SHORT/HOLD) + ציון אמון.
    לוגיקה פשוטה: RSI + ADX + EMA
    """
    rsi = row.get("rsi")
    adx = row.get("adx")
    ema = row.get("ema_21")
    close = row.get("close")

    if rsi is None or adx is None or ema is None or close is None:
        return {"signal": None, "confidence": 0, "reason": "missing indicators"}

    # תנאים:
    # RSI > 55, close > ema, adx > 20 → LONG
    # RSI < 45, close < ema, adx > 20 → SHORT
    # אחרת HOLD
    if rsi > 55 and close > ema and adx > 20:
        return {"signal": "LONG", "confidence": 0.8, "reason": "RSI high + price > EMA + ADX strong"}
    elif rsi < 45 and close < ema and adx > 20:
        return {"signal": "SHORT", "confidence": 0.8, "reason": "RSI low + price < EMA + ADX strong"}
    else:
        return {"signal": "HOLD", "confidence": 0.5, "reason": "Neutral / weak trend"}

def analyze_symbol(symbol: str, market: str = "futures", interval: str = "15m", limit: int = 200) -> Dict[str, Any]:
    try:
        df = _fetch_klines(symbol, interval, limit)
        if df.empty:
            return {"symbol": symbol, "market": market, "interval": interval, "error": "no data"}

        ind = prepare_indicators_for_backtest(df)
        if ind.empty:
            return {"symbol": symbol, "market": market, "interval": interval, "error": "indicator calc failed"}

        row = ind.iloc[-1].to_dict()
        out: Dict[str, Any] = {k: (float(v) if isinstance(v, (int, float)) else v) for k, v in row.items()}
        out.update({
            "symbol": symbol,
            "market": market,
            "interval": interval,
            "close": float(df["close"].iloc[-1]),
        })

        # אות החלטה
        signal_data = _generate_signal(out)
        out.update(signal_data)

        return out
    except Exception as e:
        return {"symbol": symbol, "market": market, "interval": interval, "error": str(e)}



