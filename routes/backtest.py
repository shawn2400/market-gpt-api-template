# routes/backtest.py
from __future__ import annotations
from typing import Dict, Any
from fastapi import APIRouter, Query, Body, HTTPException

import pandas as pd
from binance.client import Client

from utils.config import BINANCE_API_KEY, BINANCE_API_SECRET
from utils.backtest_utils import run_backtest

router = APIRouter(prefix="/backtest", tags=["Backtest"])

# Binance client (קריאה בלבד לנתונים היסטוריים)
_client = Client(api_key=BINANCE_API_KEY, api_secret=BINANCE_API_SECRET)


async def fetch_klines(symbol: str, interval: str, limit: int = 500) -> pd.DataFrame:
    """
    מוריד נרות היסטוריים מ־Binance ומחזיר כ־DataFrame מוכן.
    """
    try:
        raw = _client.get_klines(symbol=symbol, interval=interval, limit=limit)
        df = pd.DataFrame(raw, columns=[
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "qav", "num_trades", "taker_base", "taker_quote", "ignore"
        ])
        df["open"] = df["open"].astype(float)
        df["high"] = df["high"].astype(float)
        df["low"] = df["low"].astype(float)
        df["close"] = df["close"].astype(float)
        df["volume"] = df["volume"].astype(float)
        return df
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch klines for {symbol}: {e}")


@router.post("/", summary="Run Backtest", operation_id="postBacktest")
async def post_backtest(
    payload: Dict[str, Any] = Body(..., example={
        "symbol": "BTCUSDT",
        "interval": "15m",
        "limit": 500,
        "strategy": "macd_crossover",
        "initial_balance": 1000.0
    })
) -> Dict[str, Any]:
    """
    ✅ מריץ Backtest עם אסטרטגיה נבחרת:
    - ema_crossover
    - macd_crossover
    - bollinger
    """
    symbol = payload.get("symbol", "BTCUSDT")
    interval = payload.get("interval", "15m")
    limit = int(payload.get("limit", 500))
    strategy = payload.get("strategy", "ema_crossover")
    initial_balance = float(payload.get("initial_balance", 1000.0))

    df = await fetch_klines(symbol, interval, limit)
    result = run_backtest(df, strategy=strategy, initial_balance=initial_balance)
    return result











