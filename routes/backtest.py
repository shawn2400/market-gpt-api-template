# utils/backtester.py
from __future__ import annotations
import logging
import pandas as pd
from binance.client import Client
from typing import Dict, Any

from utils.config import BINANCE_API_KEY, BINANCE_API_SECRET
from utils.indicators import prepare_indicators_for_backtest

logger = logging.getLogger("algogpt.backtester")

# יצירת Binance Client
_client = Client(api_key=BINANCE_API_KEY, api_secret=BINANCE_API_SECRET)


async def fetch_klines(symbol: str, interval: str, limit: int = 500) -> pd.DataFrame:
    """
    מוריד נרות היסטוריים מ־Binance ומחזיר כ־DataFrame.
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
        logger.error(f"Failed to fetch klines for {symbol}: {e}")
        raise


async def run_backtest(
    symbol: str,
    interval: str,
    limit: int = 500,
    strategy: str = "ema_rsi",
    initial_balance: float = 1000.0,
) -> Dict[str, Any]:
    """
    מריץ סימולציית Backtest עם אסטרטגיה נתונה.
    """
    df = await fetch_klines(symbol, interval, limit)
    df = prepare_indicators_for_backtest(df)

    balance = initial_balance
    position = None
    entry_price = 0.0
    trades = []

    for i in range(50, len(df)):  # נתחיל אחרי שיש מספיק אינדיקטורים
        row = df.iloc[i]
        close = row["close"]

        if strategy == "ema_rsi":
            # כללי דוגמה: כניסה לפי EMA crossover + RSI
            if position is None:
                if row["ema21"] > row["ema50"] and row["rsi"] < 70:
                    # פתח LONG
                    position = "LONG"
                    entry_price = close
                    trades.append({"action": "BUY", "price": close, "index": i})
                elif row["ema21"] < row["ema50"] and row["rsi"] > 30:
                    # פתח SHORT
                    position = "SHORT"
                    entry_price = close
                    trades.append({"action": "SELL", "price": close, "index": i})
            else:
                # יציאה מהפוזיציה
                if position == "LONG" and (row["ema21"] < row["ema50"] or row["rsi"] > 70):
                    pnl = (close - entry_price) / entry_price * balance
                    balance += pnl
                    trades.append({"action": "CLOSE_LONG", "price": close, "pnl": pnl})
                    position = None
                elif position == "SHORT" and (row["ema21"] > row["ema50"] or row["rsi"] < 30):
                    pnl = (entry_price - close) / entry_price * balance
                    balance += pnl
                    trades.append({"action": "CLOSE_SHORT", "price": close, "pnl": pnl})
                    position = None

    return {
        "symbol": symbol,
        "interval": interval,
        "strategy": strategy,
        "final_balance": round(balance, 2),
        "profit_pct": round(((balance / initial_balance) - 1) * 100, 2),
        "num_trades": len([t for t in trades if "CLOSE" in t["action"]]),
        "trades": trades[-10:],  # נחזיר רק 10 אחרונים כדי לא להעמיס
    }










