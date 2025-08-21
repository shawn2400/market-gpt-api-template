# utils/auto_executor.py
import asyncio
import logging
import requests
import pandas as pd
import time

from utils import config as cfg
from utils.binance_client import binance_client
from utils.indicators import prepare_indicators_for_backtest

logger = logging.getLogger("algogpt.autoexec")

FUTURES_BASE = "https://fapi.binance.com"

# 🆕 משתנים גלובליים
EXECUTOR_RUNNING = False
EXECUTOR_SYMBOLS: list[str] = []
EXECUTOR_LAST_TS: float | None = None   # ✅ שומר מתי רץ לאחרונה


def is_executor_running() -> bool:
    return EXECUTOR_RUNNING


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


def start_executor():
    global EXECUTOR_RUNNING
    if EXECUTOR_RUNNING:
        logger.info("⚠️ Auto Executor already running")
        return

    logger.info("🚀 Starting Auto Executor loop ...")
    loop = asyncio.get_event_loop()
    if not loop.is_running():
        loop.run_until_complete(auto_scan_and_trade())
    else:
        loop.create_task(auto_scan_and_trade())


def stop_executor():
    global EXECUTOR_RUNNING
    if EXECUTOR_RUNNING:
        EXECUTOR_RUNNING = False
        logger.info("🛑 Auto Executor stopping ...")
    else:
        logger.info("ℹ️ Auto Executor not running")
















































































