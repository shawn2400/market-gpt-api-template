# run_executor.py

import asyncio
import argparse
import logging
import os
from dotenv import load_dotenv
from utils.scanner_utils import scan_all
from utils.trade_executor import execute_trade_live
from utils.trade_storage import get_open_trades_count
from utils.get_live_price import get_live_price
from utils.ai_analysis import predict_optimal_sl_tp

load_dotenv()
MAX_OPEN_TRADES = 4
TRENDING_SOURCE = os.getenv("TRENDING_SOURCE", "coingecko")

async def run_executor(debug=False, once=False, delay=60, min_quality=6, max_budget=100.0, market_type="futures"):
    while True:
        if get_open_trades_count() >= MAX_OPEN_TRADES:
            logging.info("🔒 יש כבר 4 טריידים פתוחים – דילוג.")
            await asyncio.sleep(delay)
            if once:
                break
            continue

        trades = await scan_all(
            symbols=[],
            market_type=market_type,
            interval="15m",
            min_quality=min_quality,
            top=1
        )

        if trades:
            trade = trades[0]
            logging.info(f"🎯 טרייד נבחר: {trade['symbol']} | איכות: {trade['quality_score']}")
            price = get_live_price(trade["symbol"])
            sltp = predict_optimal_sl_tp(trade["direction"], price)

            if not debug and price:
                execute_trade_live(
                    symbol=trade["symbol"],
                    entry=price,
                    stop=sltp["sl"],
                    tp=sltp["tp"],
                    direction=trade["direction"],
                    leverage=20,
                    budget_usd=max_budget,
                    market_type=market_type
                )
            else:
                logging.info("[DEBUG] מצב בדיקה – לא בוצעה שליחה ל־Binance")
        else:
            logging.info("⚠️ לא נמצא טרייד איכותי.")

        if once:
            break
        await asyncio.sleep(delay)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="הרצה חיה של AlgoGPT Auto Executor")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--delay", type=int, default=60)
    parser.add_argument("--min_quality", type=int, default=6)
    parser.add_argument("--budget", type=float, default=100)
    parser.add_argument("--market_type", type=str, default="futures")
    args = parser.parse_args()

    asyncio.run(run_executor(
        debug=args.debug,
        once=args.once,
        delay=args.delay,
        min_quality=args.min_quality,
        max_budget=args.budget,
        market_type=args.market_type
    ))






