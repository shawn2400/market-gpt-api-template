# routes/routes_indicators.py
from fastapi import APIRouter, HTTPException
import asyncio
import pandas as pd

router = APIRouter(prefix="/indicators", tags=["indicators"])

# ---------- Helpers ----------

def _apply_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    מנסה להעשיר אינדיקטורים אם קיימות פונקציות פנימיות; לא מפיל את הראוטר אם חסר.
    """
    try:
        from utils.indicators import compute_indicators as _compute  # type: ignore
        return _compute(df)
    except Exception:
        pass
    try:
        from utils.indicators import add_indicators as _add  # type: ignore
        return _add(df)
    except Exception:
        return df

def _is_ccxt_symbol(symbol: str) -> bool:
    # פורמט של ccxt: למשל "BNB/USDT"
    return "/" in symbol

# ---------- Data fetchers ----------

def _fetch_with_ccxt(symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
    # נטען רק אם מותקן – לא מפיל את האפליקציה בזמן import של המודול
    import ccxt  # type: ignore
    ex = ccxt.binance()
    ohlcv = ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    return df

def _fetch_with_binance_futures(symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
    # UMFutures מקבל interval כמו '1m','5m','1h','4h','1d' וכו'
    from binance.um_futures import UMFutures  # type: ignore
    um = UMFutures()  # אין צורך במפתחות לפעולות ציבוריות
    kl = um.klines(symbol=symbol, interval=timeframe, limit=limit)
    # מבנה: [ openTime, open, high, low, close, volume, closeTime, ... ]
    cols = ["openTime","open","high","low","close","volume","closeTime","qv","nTrades","takerBase","takerQuote","x"]
    df = pd.DataFrame(kl, columns=cols[:len(kl[0])])
    df = df.rename(columns={"openTime": "timestamp"})
    # טיפוסי עמודות
    for c in ("open","high","low","close","volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    return df[["timestamp","open","high","low","close","volume"]]

def _fetch_with_binance_spot(symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
    from binance import Client  # type: ignore
    interval_map = {
        "1m": Client.KLINE_INTERVAL_1MINUTE,
        "3m": Client.KLINE_INTERVAL_3MINUTE,
        "5m": Client.KLINE_INTERVAL_5MINUTE,
        "15m": Client.KLINE_INTERVAL_15MINUTE,
        "30m": Client.KLINE_INTERVAL_30MINUTE,
        "1h": Client.KLINE_INTERVAL_1HOUR,
        "2h": Client.KLINE_INTERVAL_2HOUR,
        "4h": Client.KLINE_INTERVAL_4HOUR,
        "6h": Client.KLINE_INTERVAL_6HOUR,
        "8h": Client.KLINE_INTERVAL_8HOUR,
        "12h": Client.KLINE_INTERVAL_12HOUR,
        "1d": Client.KLINE_INTERVAL_1DAY,
        "3d": Client.KLINE_INTERVAL_3DAY,
        "1w": Client.KLINE_INTERVAL_1WEEK,
        "1M": Client.KLINE_INTERVAL_1MONTH,
    }
    if timeframe not in interval_map:
        raise HTTPException(status_code=400, detail=f"unsupported timeframe for spot: {timeframe}")

    cli = Client()  # ללא מפתחות עבור public endpoints
    kl = cli.get_klines(symbol=symbol, interval=interval_map[timeframe], limit=limit)
    cols = ["openTime","open","high","low","close","volume","closeTime","qv","nTrades","takerBase","takerQuote","x"]
    df = pd.DataFrame(kl, columns=cols[:len(kl[0])])
    df = df.rename(columns={"openTime": "timestamp"})
    for c in ("open","high","low","close","volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    return df[["timestamp","open","high","low","close","volume"]]

async def _fetch_ohlcv(symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
    """
    סדר פעולות:
    1) אם הסימבול בפורמט ccxt (עם '/'): נסה ccxt → אם נכשל, 501 מוסבר.
    2) אחרת (BNBUSDT): נסה Futures (UMFutures) → אם נכשל, Spot → אם נכשל, 502.
    """
    if _is_ccxt_symbol(symbol):
        try:
            return await asyncio.to_thread(_fetch_with_ccxt, symbol, timeframe, limit)
        except Exception as e:
            raise HTTPException(status_code=501, detail=f"ccxt unavailable or fetch failed: {type(e).__name__}: {e}")

    try:
        return await asyncio.to_thread(_fetch_with_binance_futures, symbol, timeframe, limit)
    except Exception as e_fut:
        try:
            return await asyncio.to_thread(_fetch_with_binance_spot, symbol, timeframe, limit)
        except Exception as e_spot:
            raise HTTPException(
                status_code=502,
                detail=f"binance fetch failed (futures: {type(e_fut).__name__}, spot: {type(e_spot).__name__})"
            )

# ---------- Routes ----------

@router.get("/", summary="Indicators sample (sanity)")
async def indicators_sample():
    nowh = pd.Timestamp.utcnow().floor("h")
    data = [
        {"timestamp": nowh, "open": 100.0, "high": 110.0, "low": 95.0,  "close": 105.0, "volume": 12345},
        {"timestamp": nowh, "open": 105.0, "high": 115.0, "low": 100.0, "close": 110.0, "volume": 23456},
    ]
    df = pd.DataFrame(data)
    df = _apply_indicators(df)
    return df.tail(1).to_dict(orient="records")[0]

@router.get("/{symbol}", summary="Indicators from Binance/ccxt with fallback")
async def indicators_symbol(symbol: str = "BNBUSDT", timeframe: str = "1h", limit: int = 180):
    """
    פורמטים נתמכים:
    - "BNBUSDT" → Binance Futures קודם, ואז Spot fallback.
    - "BNB/USDT" → ccxt.
    """
    df = await _fetch_ohlcv(symbol=symbol, timeframe=timeframe, limit=limit)
    df = _apply_indicators(df)
    return df.tail(1).to_dict(orient="records")[0]


