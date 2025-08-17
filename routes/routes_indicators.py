# routes/routes_indicators.py
from fastapi import APIRouter, HTTPException
import pandas as pd

router = APIRouter(prefix="/indicators", tags=["indicators"])

def _apply_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    מנסה להעשיר אינדיקטורים אם קיימים מודולים פנימיים. לא מפיל את הראוטר אם חסר.
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
        return df  # fallback: תחזיר בסיס

@router.get("/", summary="Indicators sample (sanity)")
async def indicators_sample():
    # נתוני דוגמה מינימליים כדי לבדוק שהראוטר מחובר
    data = [
        {"timestamp": pd.Timestamp.utcnow().floor("h"), "open": 100.0, "high": 110.0, "low": 95.0,  "close": 105.0, "volume": 12345},
        {"timestamp": pd.Timestamp.utcnow().floor("h"), "open": 105.0, "high": 115.0, "low": 100.0, "close": 110.0, "volume": 23456},
    ]
    df = pd.DataFrame(data)
    df = _apply_indicators(df)
    return df.tail(1).to_dict(orient="records")[0]

@router.get("/{symbol}", summary="Indicators from exchange via ccxt (if available)")
async def indicators_symbol(symbol: str = "BNB/USDT", timeframe: str = "1h", limit: int = 180):
    """
    ננסה להביא OHLCV מ־ccxt אם זמין. אם לא — נחזיר 501 ולא נפיל את השרת.
    NB: סימבול בפורמט ccxt (למשל 'BNB/USDT').
    """
    try:
        import ccxt  # type: ignore
        ex = ccxt.binance()
        ohlcv = ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df = _apply_indicators(df)
        return df.tail(1).to_dict(orient="records")[0]
    except Exception as e:
        raise HTTPException(status_code=501, detail=f"ccxt unavailable or fetch failed: {type(e).__name__}: {e}")
