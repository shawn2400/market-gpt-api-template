# routes/routes_indicators.py
from fastapi import APIRouter, HTTPException, Query
import asyncio
import pandas as pd

router = APIRouter(prefix="/indicators", tags=["indicators"])

# ---------- Indicators helper ----------

def _apply_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    מנסה לחשב אינדיקטורים אם קיימת פונקציה פנימית.
    לא מפיל את הראוטר אם חסרה — פשוט יחזיר רק OHLCV.
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

# ---------- Fetch helpers ----------

def _is_ccxt_symbol(symbol: str) -> bool:
    # פורמט של ccxt: למשל "BNB/USDT"
    return "/" in symbol

def _fetch_with_ccxt(symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
    try:
        import ccxt  # נטען רק אם קיים
    except Exception as e:
        raise HTTPException(status_code=501, detail=f"ccxt unavailable: {type(e).__name__}: {e}")

    ex = ccxt.binance()
    ohlcv = ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit) or []
    if not ohlcv:
        raise HTTPException(status_code=404, detail=f"no data from ccxt for {symbol}@{timeframe}")

    df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    return df

def _fetch_with_binance_futures(symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
    from binance.um_futures import UMFutures
    um = UMFutures()  # אין צורך במפתחות לפעולות ציבוריות
    kl = um.klines(symbol=symbol, interval=timeframe, limit=limit) or []
    if not kl:
        raise HTTPException(status_code=404, detail=f"no futures data for {symbol}@{timeframe}")

    # מבנה: [ openTime, open, high, low, close, volume, closeTime, ... ]
    cols = ["openTime","open","high","low","close","volume","closeTime","qv","nTrades","takerBase","takerQuote","x"]
    df = pd.DataFrame(kl, columns=cols[:len(kl[0])]).rename(columns={"openTime": "timestamp"})
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df[["timestamp", "open", "high", "low", "close", "volume"]]
    return df

def _fetch_with_binance_spot(symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
    from binance import Client
    interval_map = {
        "1m": Client.KLINE_INTERVAL_1MINUTE,  "3m": Client.KLINE_INTERVAL_3MINUTE,
        "5m": Client.KLINE_INTERVAL_5MINUTE,  "15m": Client.KLINE_INTERVAL_15MINUTE,
        "30m": Client.KLINE_INTERVAL_30MINUTE,"1h": Client.KLINE_INTERVAL_1HOUR,
        "2h": Client.KLINE_INTERVAL_2HOUR,    "4h": Client.KLINE_INTERVAL_4HOUR,
        "6h": Client.KLINE_INTERVAL_6HOUR,    "8h": Client.KLINE_INTERVAL_8HOUR,
        "12h": Client.KLINE_INTERVAL_12HOUR,  "1d": Client.KLINE_INTERVAL_1DAY,
        "3d": Client.KLINE_INTERVAL_3DAY,     "1w": Client.KLINE_INTERVAL_1WEEK,
        "1M": Client.KLINE_INTERVAL_1MONTH,
    }
    if timeframe not in interval_map:
        raise HTTPException(status_code=400, detail=f"unsupported spot timeframe: {timeframe}")

    cli = Client()  # ללא מפתחות עבור public endpoints
    kl = cli.get_klines(symbol=symbol, interval=interval_map[timeframe], limit=limit) or []
    if not kl:
        raise HTTPException(status_code=404, detail=f"no spot data for {symbol}@{timeframe}")

    cols = ["openTime","open","high","low","close","volume","closeTime","qv","nTrades","takerBase","takerQuote","x"]
    df = pd.DataFrame(kl, columns=cols[:len(kl[0])]).rename(columns={"openTime": "timestamp"})
    for c in ("open","high","low","close","volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df[["timestamp","open","high","low","close","volume"]]
    return df

async def _fetch_ohlcv(symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
    """
    אסטרטגיית הבאה:
    1) אם הסימבול בפורמט ccxt (עם '/'): נסה ccxt → אם נכשל/אין נתונים → 501/404.
    2) אחרת (BNBUSDT): נסה Futures (UMFutures) → אם נכשל/ריק, נסה Spot → אם נכשל/ריק → 502/404.
    הקריאות חוסמות רצות ב-threadpool (asyncio.to_thread) כדי לא לחסום את ה-event loop.
    """
    # CCXT path
    if _is_ccxt_symbol(symbol):
        return await asyncio.to_thread(_fetch_with_ccxt, symbol, timeframe, limit)

    # Binance Futures (עדיף ל־USDT Perp), ואז Spot כ־fallback
    try:
        return await asyncio.to_thread(_fetch_with_binance_futures, symbol, timeframe, limit)
    except HTTPException as e_fut:
        # אם זו שגיאת 404 — ננסה ספוט; אם ספוט גם נכשל נחזיר את שגיאת הספוט
        try:
            return await asyncio.to_thread(_fetch_with_binance_spot, symbol, timeframe, limit)
        except HTTPException as e_spot:
            # אם שתי הקריאות כשלו — נחזיר את הספוט אם 404, אחרת 502 כללית
            if e_spot.status_code == 404:
                raise
            raise HTTPException(status_code=502, detail=f"binance fetch failed (futures: {e_fut.detail}, spot: {e_spot.detail})")
    except Exception as e_fut:
        # כל שגיאה אחרת בפיוצ'רס → ננסה ספוט
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
    data = [
        {"timestamp": pd.Timestamp.utcnow().floor("h"), "open": 100.0, "high": 110.0, "low": 95.0,  "close": 105.0, "volume": 12345},
        {"timestamp": pd.Timestamp.utcnow().floor("h"), "open": 105.0, "high": 115.0, "low": 100.0, "close": 110.0, "volume": 23456},
    ]
    df = pd.DataFrame(data)
    df = _apply_indicators(df)
    return df.tail(1).to_dict(orient="records")[0]

@router.get("/{symbol:path}", summary="Indicators from Binance/ccxt with fallback")
async def indicators_symbol(
    symbol: str = "BNBUSDT",
    timeframe: str = Query("1h", description="Binance/ccxt interval, e.g. 1m, 15m, 1h, 4h, 1d"),
    limit: int = Query(180, ge=10, le=2000, description="Number of candles to fetch")
):
    df = await _fetch_ohlcv(symbol=symbol, timeframe=timeframe, limit=limit)
    if df.empty:
        raise HTTPException(status_code=404, detail="empty dataframe")
    df = _apply_indicators(df)
    return df.tail(1).to_dict(orient="records")[0]





