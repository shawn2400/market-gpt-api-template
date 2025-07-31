# run_executor.py

import asyncio
import argparse
import logging
import os
import time
from dotenv import load_dotenv

from utils.scanner_utils import scan_all
from utils.trade_executor import execute_trade_live
from utils.trade_storage import get_open_trades_count

load_dotenv()

MAX_OPEN_TRADES = 4
TRENDING_SOURCE = os.getenv("TRENDING_SOURCE", "coingecko")

async def run_executor(
    debug: bool = False,
    once: bool = False,
    delay: int = 60,
    min_quality: int = 6,
    max_budget: float = 100.0,
    market_type: str = "futures"
):
    if get_open_trades_count() >= MAX_OPEN_TRADES:
        logging.info("🔒 יש כבר 4 טריידים פתוחים – דילוג.")
        return

    async def run_once():
        best_trade = None
        markets = ["futures", "spot", "grid"]

        for market in markets:
            logging.info(f"[RUN_EXECUTOR] 🚀 scanning market: {market}")
            trades = scan_all(
                market=market,
                min_quality=min_quality,
                top=1,
                trending_source=TRENDING_SOURCE
            )
            if trades:
                trade = trades[0]
                if not best_trade or trade["quality_score"] > best_trade["quality_score"]:
                    best_trade = trade

        if best_trade:
            logging.info(f"🎯 טרייד נבחר: {best_trade['symbol']} | איכות: {best_trade['quality_score']}")
            if not debug:
                execute_trade_live(best_trade, budget=max_budget, leverage=best_trade.get("leverage", 20))
            else:
                logging.info("[DEBUG] מצב בדיקה – לא מבוצעת שליחה ל־Binance")
        else:
            logging.info("⚠️ לא נמצא טרייד איכותי.")

    if once:
        await run_once()
    else:
        while True:
            await run_once()
            await asyncio.sleep(delay)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="הרצה חיה של AlgoGPT Auto Executor")
    parser.add_argument("--debug", action="store_true", help="מצב בדיקה - ללא שליחה ל־Binance")
    parser.add_argument("--once", action="store_true", help="הרצה חד פעמית בלבד")
    parser.add_argument("--delay", type=int, default=60, help="השהיה בין הרצות (שניות)")
    parser.add_argument("--min_quality", type=int, default=6, help="סף מינימלי לציון איכות")
    parser.add_argument("--budget", type=float, default=100, help="תקציב לטרייד (USDT)")
    parser.add_argument("--market_type", type=str, default="futures", help="futures/spot/grid")
    args = parser.parse_args()

    asyncio.run(run_executor(
        debug=args.debug,
        once=args.once,
        delay=args.delay,
        min_quality=args.min_quality,
        max_budget=args.budget,
        market_type=args.market_type
    ))






