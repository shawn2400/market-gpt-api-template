# run_executor.py

import asyncio
import argparse
from auto_executor import run_executor

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="הרצה חיה של AlgoGPT Auto Executor")
    parser.add_argument("--debug", action="store_true", help="מצב בדיקה - ללא שליחה ל־Binance")
    parser.add_argument("--once", action="store_true", help="הרצה חד פעמית בלבד")
    parser.add_argument("--delay", type=int, default=60, help="השהיה בין הרצות (שניות)")
    parser.add_argument("--min_quality", type=int, default=6, help="סף מינימלי לציון איכות")
    parser.add_argument("--budget", type=float, default=100, help="תקציב לטרייד (USDT)")
    parser.add_argument("--market_type", type=str, default="futures", help="futures/spot")
    args = parser.parse_args()

    asyncio.run(run_executor(
        debug=args.debug,
        once=args.once,
        delay=args.delay,
        min_quality=args.min_quality,
        max_budget=args.budget,
        market_type=args.market_type
    ))




