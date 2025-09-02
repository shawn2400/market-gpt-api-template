import asyncio
import os
import time

from utils.multi_tf_scanner import multi_tf_scan_with_ai
from utils.trade_executor import execute_trade_live
from utils.trade_storage import save_trade_payload
from utils.watchlist_utils import load_watchlist
from utils.ai_analysis import predict_optimal_sl_tp

AUTO_RUN = os.getenv("AUTO_RUN", "false").lower() == "true"
MIN_SCORE = float(os.getenv("MIN_QUALITY_SCORE", 8.5))
MAX_TRADE_BUDGET = float(os.getenv("MAX_TRADE_BUDGET", 100))
SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", 60))


async def auto_executor_loop():
    if not AUTO_RUN:
        print("[AutoExecutor] Skipped – AUTO_RUN is disabled.")
        return

    print("[AutoExecutor] Started ✓")
    symbols = load_watchlist()
    while True:
        try:
            print("[AutoExecutor] Scanning watchlist...", flush=True)
            results = await multi_tf_scan_with_ai(symbols)

            for result in results:
                if result.get("score", 0) < MIN_SCORE:
                    continue

                symbol = result["symbol"]
                direction = result["direction"]
                interval = result.get("interval", "15m")

                sl, tp = await predict_optimal_sl_tp(symbol, interval, direction)
                
                payload = {
                    "symbol": symbol,
                    "side": direction,
                    "budget": MAX_TRADE_BUDGET,
                    "sl": sl,
                    "tp": tp,
                    "leverage": None,
                    "interval": interval,
                    "dry_run": False
                }

                response = await execute_trade_live(payload)
                save_trade_payload(payload, response)

                print(f"[AutoExecutor] Executed {symbol} {direction} with SL={sl} TP={tp}")

        except Exception as e:
            print(f"[AutoExecutor] Error: {e}", flush=True)

        await asyncio.sleep(SCAN_INTERVAL)


def start_auto_executor():
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(auto_executor_loop())
        else:
            loop.run_until_complete(auto_executor_loop())
    except RuntimeError:
        asyncio.run(auto_executor_loop())



















































































