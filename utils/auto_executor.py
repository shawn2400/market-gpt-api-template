# utils/auto_executor.py
import asyncio
import logging
from utils import config as cfg
from utils.binance_client import binance_client
from utils.indicators import prepare_indicators_for_backtest
import requests
import pandas as pd

logger = logging.getLogger("algogpt.autoexec")

FUTURES_BASE = "https://fapi.binance.com"

def fetch_klines(symbol: str, interval: str = "15m", limit: int = 200) -> pd.DataFrame:
    """
    מושך נתוני Klines מ-Binance
    """
    url = f"{FUTURES_BASE}/fapi/v1/klines"
    r = requests.get(url, params={"symbol": symbol, "interval": interval, "limit": limit}, timeout=10)
    r.raise_for_status()
    arr = r.json()
    cols = ["open_time","open","high","low","close","volume","close_time","qv","nTrades","taker_base","taker_quote","x"]
    df = pd.DataFrame(arr, columns=cols[:len(arr[0])])
    for c in ("open","high","low","close","volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df[["open","high","low","close","volume"]]

async def scan_and_trade(symbol: str):
    try:
        df = fetch_klines(symbol)
        ind = prepare_indicators_for_backtest(df)
        if ind.empty:
            logger.warning(f"[auto] No data for {symbol}")
            return

        last = ind.iloc[-1]
        rsi = float(last.get("rsi", 50))
        close = float(last.get("close", df["close"].iloc[-1]))

        logger.info(f"[auto] {symbol} RSI={rsi:.2f}, Close={close}")

        if rsi < 30:
            # קניה (LONG)
            qty = round(cfg.MAX_TRADE_BUDGET / close, 3)
            order = binance_client.new_order(
                symbol=symbol,
                side="BUY",
                type="MARKET",
                quantity=qty,
            )
            logger.info(f"[auto] LONG {symbol} → {order}")
        elif rsi > 70:
            # מכירה (SHORT)
            qty = round(cfg.MAX_TRADE_BUDGET / close, 3)
            order = binance_client.new_order(
                symbol=symbol,
                side="SELL",
                type="MARKET",
                quantity=qty,
            )
            logger.info(f"[auto] SHORT {symbol} → {order}")
        else:
            logger.info(f"[auto] {symbol} → No trade signal")

    except Exception as e:
        logger.error(f"[auto] Error for {symbol}: {e}")

async def auto_scan_and_trade():
    """
    סורק ומבצע טריידים על כל הסימבולים ב-WATCHLIST
    """
    while True:
        for symbol in cfg.WATCHLIST:
            await scan_and_trade(symbol)
        await asyncio.sleep(cfg.SCAN_INTERVAL)

def start_executor():
    logger.info("🚀 Starting Auto Executor loop ...")
    loop = asyncio.get_event_loop()
    if not loop.is_running():
        loop.run_until_complete(auto_scan_and_trade())
    else:
        loop.create_task(auto_scan_and_trade())













































































