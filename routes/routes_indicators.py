from fastapi import APIRouter
import pandas as pd
import ccxt
from indicators import add_indicators

router = APIRouter()

@router.get("/indicators/{symbol}")
def get_indicators(symbol: str = "BNBUSDT", timeframe: str = "1h", limit: int = 100):
    exchange = ccxt.binance()
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)

    df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")

    df = add_indicators(df)
    return df.tail(1).to_dict(orient="records")[0]
