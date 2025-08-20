# utils/auto_executor.py
import asyncio
import logging
import time
from utils import config as cfg
from utils.binance_client import binance_client

logger = logging.getLogger("algogpt.autoexec")

async def auto_scan_and_trade():
    """
    סורק את המטבעות ב־WATCHLIST ומבצע טריידים אם יש סיגנל
    """
    while True:
        try:
            # דוגמה: סריקה בסיסית
            for symbol in cfg.WATCHLIST:
                # TODO: לקרוא פונקציית analyze ולבדוק quality_score
                logger.info(f"[auto] Scanning {symbol} ...")
                # כאן אפשר לשלב קריאת /ai/manual-scan או אינדיקטורים
                # ואז לבצע טרייד אם התנאים מתקיימים
            await asyncio.sleep(cfg.SCAN_INTERVAL)
        except Exception as e:
            logger.error(f"Auto executor error: {e}")
            await asyncio.sleep(10)

def start_executor():
    logger.info("Starting Auto Executor loop ...")
    loop = asyncio.get_event_loop()
    if not loop.is_running():
        loop.run_until_complete(auto_scan_and_trade())
    else:
        loop.create_task(auto_scan_and_trade())












































































