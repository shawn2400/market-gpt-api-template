# utils/auto_executor.py
import asyncio
import logging
import requests
import pandas as pd
import time
from collections import deque

from utils import config as cfg
from utils.binance_client import binance_client
from utils.indicators import prepare_indicators_for_backtest

logger = logging.getLogger("algogpt.autoexec")

FUTURES_BASE = "https://fapi.binance.com"

# 🆕 משתנים גלובליים
EXECUTOR_RUNNING = False
EXECUTOR_SYMBOLS: list[str] = []
EXECUTOR_LAST_TS: float | None = None   # ✅ שומר מתי רץ לאחרונה
EXECUTOR_LOGS: deque[dict] = deque(maxlen=200)  # ✅ לוגים בזיכרון


def _log(event: str, symbol: str | None = None, level: str = "INFO", **kwargs):
    """
    מוסיף גם ללוג של Python וגם ל־buffer בזיכרון
    """
    record = {
        "time": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
        "event": event,
        "symbol": symbol,
        "level": level,
        **kwargs,
    }
    EXECUTOR_LOGS.append(record)

    if level == "ERROR":
        logger.error(record)
    elif level == "WARNING":
        logger.warning(record)
    else:
        logger.info(record)


def is_executor_running() -> bool:
    return EXECUTOR_RUNNING


async def scan_and_trade(symbol: str):
    try:
        _log("scan_start", symbol=symbol)
        url = f"{FUTURES_BASE}/fapi/v1/klines"
        r = requests.get(url, params={"symbol": symbol, "interval": "15m", "limit": 200}, timeout=10)
        r.raise_for_status()
        arr = r.json()

        cols = ["open_time","open","high","low","close","volume","close_time","qv","nTrades","taker_base","taker_quote","x"]
        df = pd.DataFrame(arr, columns=cols[:len(arr[0])])
        for c in ("open","high","low","close","volume"):
            df[c] = pd.to_numeric(df[c], errors="coerce")

        ind = prepare_indicators_for_backtest(df)
        if ind.empty:
            _log("scan_no_data", symbol=symbol, level="WARNING")
            return

        row = ind.iloc[-1].to_dict()
        _log("scan_ok", symbol=symbol, indicators=row)

    except Exception as e:
        _log("scan_error", symbol=symbol, level="ERROR", error=str(e))


# ---------------------------------------------------
# Executor loop
# ---------------------------------------------------
async def auto_scan_and_trade():
    global EXECUTOR_RUNNING, EXECUTOR_SYMBOLS, EXECUTOR_LAST_TS
    EXECUTOR_RUNNING = True
    try:
        while EXECUTOR_RUNNING:
            EXECUTOR_LAST_TS = time.time()   # ⏱️ מתעדכן כל מחזור
            EXECUTOR_SYMBOLS = [s.upper() for s in cfg.WATCHLIST]
            if "BTCUSDT" not in EXECUTOR_SYMBOLS:
                EXECUTOR_SYMBOLS.insert(0, "BTCUSDT")

            for symbol in EXECUTOR_SYMBOLS:
                await scan_and_trade(symbol)

            await asyncio.sleep(cfg.SCAN_INTERVAL)
    finally:
        EXECUTOR_RUNNING = False
        EXECUTOR_SYMBOLS = []
        EXECUTOR_LAST_TS = None
        _log("executor_stopped", level="INFO")


def start_executor():
    global EXECUTOR_RUNNING
    if EXECUTOR_RUNNING:
        _log("executor_already_running")
        return

    _log("executor_starting")
    loop = asyncio.get_event_loop()
    if not loop.is_running():
        loop.run_until_complete(auto_scan_and_trade())
    else:
        loop.create_task(auto_scan_and_trade())


def stop_executor():
    global EXECUTOR_RUNNING
    if EXECUTOR_RUNNING:
        EXECUTOR_RUNNING = False
        _log("executor_stopping")
    else:
        _log("executor_not_running")
















































































