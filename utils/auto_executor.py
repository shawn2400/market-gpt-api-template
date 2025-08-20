# utils/auto_executor.py
import asyncio
import logging
import requests
import pandas as pd

from utils import config as cfg
from utils.binance_client import binance_client
from utils.indicators import prepare_indicators_for_backtest

logger = logging.getLogger("algogpt.autoexec")

FUTURES_BASE = "https://fapi.binance.com"

# ---------------------------------------------------
# Binance Klines fetcher
# ---------------------------------------------------
def fetch_klines(symbol: str, interval: str = "15m", limit: int = 200) -> pd.DataFrame:
    url = f"{FUTURES_BASE}/fapi/v1/klines"
    r = requests.get(url, params={"symbol": symbol, "interval": interval, "limit": limit}, timeout=10)
    r.raise_for_status()
    arr = r.json()
    cols = [
        "open_time","open","high","low","close","volume","close_time",
        "qv","nTrades","taker_base","taker_quote","x"
    ]
    df = pd.DataFrame(arr, columns=cols[:len(arr[0])])
    for c in ("open","high","low","close","volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df[["open","high","low","close","volume"]]

# ---------------------------------------------------
# Auto Executor logic
# ---------------------------------------------------
def calc_leverage(rsi: float, adx: float) -> int:
    """
    מינוף דינמי 5×–35× לפי איכות:
    - ADX חזק + RSI קיצוני = יותר מינוף
    - אחרת → מינוף שמרני
    """
    score = 0
    if adx > 25: score += 1
    if adx > 30: score += 1
    if rsi < 20 or rsi > 80: score += 2
    elif rsi < 30 or rsi > 70: score += 1

    lev = 5 + score * 5
    return min(max(5, lev), 35)

async def scan_and_trade(symbol: str):
    try:
        df = fetch_klines(symbol)
        ind = prepare_indicators_for_backtest(df)
        if ind.empty:
            logger.warning(f"[auto] No data for {symbol}")
            return

        last = ind.iloc[-1]
        rsi = float(last.get("rsi", 50))
        adx = float(last.get("adx", 20))
        atr = float(last.get("atr", 0))
        close = float(last.get("close", df['close'].iloc[-1]))

        lev = calc_leverage(rsi, adx)
        logger.info(f"[auto] {symbol} RSI={rsi:.2f}, ADX={adx:.2f}, ATR={atr:.3f}, Close={close}, Lev={lev}x")

        qty = round(cfg.MAX_TRADE_BUDGET / close * lev, 3)
        stop_dist = atr * 1.5  # SL/TP distance
        entry = close

        if rsi < 30:
            sl = entry - stop_dist
            tp = entry + stop_dist
            order = place_futures_order(symbol, "LONG", qty, entry, sl, tp, lev)
            logger.info(f"[auto] LONG {symbol} @ {entry} → SL {sl}, TP {tp}, order={order}")

        elif rsi > 70:
            sl = entry + stop_dist
            tp = entry - stop_dist
            order = place_futures_order(symbol, "SHORT", qty, entry, sl, tp, lev)
            logger.info(f"[auto] SHORT {symbol} @ {entry} → SL {sl}, TP {tp}, order={order}")

        else:
            logger.info(f"[auto] {symbol} → No trade signal")

    except Exception as e:
        logger.error(f"[auto] Error for {symbol}: {e}")

def place_futures_order(symbol: str, side: str, qty: float, entry: float, sl: float, tp: float, lev: int):
    """
    פותח פוזיציית Futures עם מינוף + SL/TP
    """
    try:
        # מגדיר מינוף דינמי
        binance_client.futures_change_leverage(symbol=symbol, leverage=lev)

        # כניסה לפוזיציה
        order = binance_client.futures_create_order(
            symbol=symbol,
            side="BUY" if side == "LONG" else "SELL",
            type="LIMIT",
            timeInForce="GTC",
            price=round(entry, 2),
            quantity=qty,
        )

        # Stop Loss
        binance_client.futures_create_order(
            symbol=symbol,
            side="SELL" if side == "LONG" else "BUY",
            type="STOP_MARKET",
            stopPrice=round(sl, 2),
            closePosition=True,
        )

        # Take Profit
        binance_client.futures_create_order(
            symbol=symbol,
            side="SELL" if side == "LONG" else "BUY",
            type="TAKE_PROFIT_MARKET",
            stopPrice=round(tp, 2),
            closePosition=True,
        )

        return order
    except Exception as e:
        logger.error(f"[auto] Futures order failed for {symbol}: {e}")
        return None

# ---------------------------------------------------
# Executor loop
# ---------------------------------------------------
async def auto_scan_and_trade():
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














































































