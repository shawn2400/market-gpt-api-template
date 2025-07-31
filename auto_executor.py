# auto_executor.py

import os
import time
import logging
import asyncio
from dotenv import load_dotenv

from utils.scanner_utils import scan_all
from utils.trade_executor import execute_trade_live
from utils.trade_storage import get_open_trades_count

load_dotenv()

# === הגדרות קבועות ===
DEBUG = os.getenv("DEBUG", "false").lower() == "true"
AUTO_RUN = os.getenv("AUTO_RUN", "false").lower() == "true"
DELAY = int(os.getenv("AUTO_RUN_DELAY", 60))
MIN_QUALITY_SCORE = int(os.getenv("MIN_QUALITY_SCORE", 6))
MAX_OPEN_TRADES = int(os.getenv("MAX_OPEN_TRADES", 4))
BUDGET = float(os.getenv("MAX_TRADE_BUDGET", 100))
TRENDING_SOURCE = os.getenv("TRENDING_SOURCE", "coingecko")

_executor_running = False
_executor_task = None

# === פונקציות בקרה חיצונית ===
def is_executor_running():
    return _executor_running

def stop_executor_loop():
    global _executor_running
    _executor_running = False
    logging.info("🛑 הופסק Auto Executor")

async def start_executor_loop():
    global _executor_running
    if _executor_running:
        logging.info("🔁 Auto executor כבר רץ.")
        return

    _executor_running = True
    logging.info("🚀 התחלת לולאת Auto Executor")

    while _executor_running:
        try:
            if get_open_trades_count() >= MAX_OPEN_TRADES:
                logging.info("🔒 יש כבר יותר מדי טריידים פתוחים – דילוג.")
                await asyncio.sleep(DELAY)
                continue

            best_trade = None
            markets = ["futures", "spot", "grid"]

            for market in markets:
                logging.info(f"[AUTO_EXECUTOR] סריקה בשוק: {market}")
                trades = await scan_all(
                    market_type=market,
                    interval="1m",
                    limit=50,
                    min_quality=MIN_QUALITY_SCORE,
                    trending_only=True,
                    trending_source=TRENDING_SOURCE,
                    min_volume=1_000_000,
                    with_ai=True,
                    top=1
                )
                if trades:
                    trade = trades[0]
                    if not best_trade or trade["quality_score"] > best_trade["quality_score"]:
                        best_trade = trade

            if best_trade:
                logging.info(f"🎯 טרייד נבחר: {best_trade['symbol']} | איכות: {best_trade['quality_score']}")
                execute_trade_live(
                    symbol=best_trade["symbol"],
                    entry=best_trade["entry"],
                    stop=best_trade["stop"],
                    tp=best_trade["tp"],
                    direction=best_trade["direction"],
                    leverage=best_trade.get("leverage", 20),
                    budget=BUDGET,
                    use_grid=best_trade.get("use_grid", False),
                    use_trailing=best_trade.get("use_trailing", False),
                    user_id="auto",
                    take_snapshot=True
                )
            else:
                logging.info("⚠️ לא נמצאו טריידים איכותיים בסבב זה.")

        except Exception as e:
            logging.exception(f"[AUTO_EXECUTOR] ❌ שגיאה במהלך הרצה: {e}")

        await asyncio.sleep(DELAY)














































