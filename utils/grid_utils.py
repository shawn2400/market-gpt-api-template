# utils/get_klines.py

import pandas as pd
from binance import AsyncClient
from typing import Literal
import asyncio
import logging

logging.basicConfig(level=logging.INFO)

async def get_klines(symbol: str, interval: str = "5m", limit: int = 150, market_type: Literal["spot", "futures"] = "futures") -> pd.DataFrame:
    """
    מחזיר DataFrame עם נתוני OHLCV מ-Binance ל־symbol המבוקש.
    תומך ב־spot ו־futures. AsyncClient חובה.
    """
    try:
        client = await AsyncClient.create()

        if market_type == "futures":
            raw = await client.futures_klines(symbol=symbol, interval=interval, limit=limit)
        else:
            raw = await client.get_klines(symbol=symbol, interval=interval, limit=limit)

        await client.close_connection()

        df = pd.DataFrame(raw, columns=[
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "quote_asset_volume", "number_of_trades",
            "taker_buy_base_asset_volume", "taker_buy_quote_asset_volume", "ignore"
        ])

        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
        df.set_index("open_time", inplace=True)

        numeric_columns = ["open", "high", "low", "close", "volume"]
        df[numeric_columns] = df[numeric_columns].astype(float)

        # שמירה רק על העמודות הקריטיות
        return df[numeric_columns]

    except Exception as e:
        logging.error(f"get_klines error for {symbol}: {e}")
        return pd.DataFrame()







