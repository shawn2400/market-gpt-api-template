# auto_executor.py

import os
import time
import logging
from utils.scan_futures import scan_all
from utils.trade_executor import execute_trade_live
from utils.trade_storage import get_open_trades_count
from dotenv import load_dotenv

load_dotenv()

DEBUG = bool(os.getenv("DEBUG", False))
AUTO_RUN = bool(os.getenv("AUTO_RUN", True))
DELAY = int(os.getenv("AUTO_RUN_DELAY", 60))
MIN_QUALITY_SCORE = int(os.getenv("MIN_QUALITY_SCORE", 6))
MAX_OPEN_TRADES = 4
BUDGET = float(os.getenv("MAX_TRADE_BUDGET", 100))
TRENDING_SOURCE = os.getenv("TRENDING_SOURCE", "coingecko")

def auto_executor_loop():
    while AUTO_RUN:
        try:
            if get_open_trades_count() >= MAX_OPEN_TRADES:
                logging.info("🔒 יש כבר 4 טריידים פתוחים – דילוג.")
                time.sleep(DELAY)
                continue

            markets = ["futures", "spot", "grid"]
            best_trade = None

            for market in markets:
                logging.info(f"[AUTO_EXECUTOR] 🚀 scanning market: {market}")
                trades = scan_all(
                    market=market,
                    min_quality=MIN_QUALITY_SCORE,
                    top=1,
                    trending_source=TRENDING_SOURCE
                )

                if trades:
                    trade = trades[0]
                    if not best_trade or trade["quality_score"] > best_trade["quality_score"]:
                        best_trade = trade

            if best_trade:
                logging.info(f"🎯 טרייד נבחר: {best_trade['symbol']} | ציון: {best_trade['quality_score']}")
                execute_trade_live(best_trade, budget=BUDGET, leverage=best_trade.get("leverage", 20))
            else:
                logging.info("⚠️ לא נמצא טרייד איכותי בסריקה זו.")

        except Exception as e:
            logging.exception(f"[AUTO_EXECUTOR] ❌ שגיאה: {type(e).__name__} – {e}")

        time.sleep(DELAY)








































