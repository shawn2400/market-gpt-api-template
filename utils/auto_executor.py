import asyncio
import logging
import time
from typing import Optional

from utils import config as cfg
from utils.indicators import prepare_indicators_for_backtest
from utils.binance_client import binance_client

logger = logging.getLogger("algogpt.autoexec")

FUTURES_BASE = "https://fapi.binance.com"

# 🆕 משתנים גלובליים
EXECUTOR_RUNNING: bool = False
EXECUTOR_SYMBOLS: list[str] = []
EXECUTOR_LAST_TS: Optional[float] = None
_EXECUTOR_TASK: Optional[asyncio.Task] = None   # ✅ task reference


def is_executor_running() -> bool:
    return EXECUTOR_RUNNING


# ---------------------------------------------------
# Scan logic (dummy, צריך להיות ממומש אצלך)
# ---------------------------------------------------
async def scan_and_trade(symbol: str):
    """
    כאן מתבצע ניתוח + טרייד בפועל (ממומש אצלך).
    """
    try:
        # דוגמא ללוג
        logger.info(f"[auto] scanning {symbol}")
        await asyncio.sleep(0.1)
    except Exception as e:
        logger.error(f"[auto] error in scan_and_trade({symbol}): {e}")


# ---------------------------------------------------
# Executor loop
# ---------------------------------------------------
async def auto_scan_and_trade():
    global EXECUTOR_RUNNING, EXECUTOR_SYMBOLS, EXECUTOR_LAST_TS
    EXECUTOR_RUNNING = True
    try:
        while EXECUTOR_RUNNING:
            EXECUTOR_LAST_TS = time.time()
            EXECUTOR_SYMBOLS = [s.upper() for s in cfg.WATCHLIST]
            if "BTCUSDT" not in EXECUTOR_SYMBOLS:
                EXECUTOR_SYMBOLS.insert(0, "BTCUSDT")

            for symbol in EXECUTOR_SYMBOLS:
                try:
                    await asyncio.wait_for(scan_and_trade(symbol), timeout=10.0)
                except asyncio.TimeoutError:
                    logger.warning(f"[auto] {symbol} scan timed out")
                except Exception as e:
                    logger.error(f"[auto] error {symbol}: {e}")

            await asyncio.sleep(cfg.SCAN_INTERVAL)
    finally:
        EXECUTOR_RUNNING = False
        EXECUTOR_SYMBOLS = []
        EXECUTOR_LAST_TS = None


def start_executor():
    """
    מפעיל את ה־executor בלולאה קיימת (async).
    """
    global _EXECUTOR_TASK, EXECUTOR_RUNNING
    if EXECUTOR_RUNNING and _EXECUTOR_TASK and not _EXECUTOR_TASK.done():
        logger.info("⚠️ Auto Executor already running")
        return

    loop = asyncio.get_event_loop()
    logger.info("🚀 Starting Auto Executor loop ...")
    _EXECUTOR_TASK = loop.create_task(auto_scan_and_trade())


def stop_executor():
    """
    עוצר את ה־executor בצורה נקייה.
    """
    global EXECUTOR_RUNNING, _EXECUTOR_TASK
    if EXECUTOR_RUNNING:
        EXECUTOR_RUNNING = False
        if _EXECUTOR_TASK and not _EXECUTOR_TASK.done():
            _EXECUTOR_TASK.cancel()
        logger.info("🛑 Auto Executor stopping ...")
    else:
        logger.info("ℹ️ Auto Executor not running")
















































































