# auto_executor.py

import os
import time
import logging
import asyncio
from dotenv import load_dotenv

from utils.scanner_utils import scan_all
from utils.trade_executor import execute_trade_live
from utils.trade_storage import get_open_trades_count

# טעינת משתני סביבה
load_dotenv()

DEBUG = os.getenv("DEBUG", "false").lower() == "true"
AUTO_RUN = os.getenv("AUTO_RUN", "false").lower() == "true"
DELAY = int(os.getenv("AUTO_RUN_DELAY", 60))
MIN_QUALITY_SCORE = int(os.getenv("MIN_QUALITY_SCORE", 6))
MAX_OPEN_TRADES = int(os.getenv("MAX_OPEN_TRADES", 4))
BUDGET = float(os.getenv("MAX_TRADE_BUDGET", 100))
TRENDING_SOURCE = os.getenv("TRENDING_SOURCE", "coingecko")

_executor_running = False

def is_executor_running():
    return _executor_running

def stop_executor_loop():
    global _executor_running
    _executor_running = False
    logging.info("🛑 הופסקה לולאת Auto Executor")

async def start_executor_loop():
    global _executor_running
    if _executor_running:
        logging.info("🔁 Auto executor כבר פעיל.")
        return

    _executor_running = True
    logging.info("🚀 התחלת לולאת Auto Executor")

    while _executor_running:
        try:
            if get_open_trades_count() >= MAX_OPEN_TRADES:

























