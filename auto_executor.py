# auto_executor.py

import threading
import asyncio
import logging
from utils.scanner_utils import scan_all
from utils.get_live_price import get_live_price
from utils.ai_analysis import predict_optimal_sl_tp
from utils.trade_executor import execute_trade_live
from utils.pnl_tracker import update_pnl
from utils.trade_storage import get_open_trades_count

executor_thread = None
executor_stop = False
MAX_OPEN_TRADES = 4

def start_executor_loop(debug=False, once=False, delay=30, min_quality=7, budget=250):
    global executor_thread, executor_stop
    if executor_thread and executor_thread.is_alive():
        return False
    executor_stop = False

    def run_loop():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(executor_loop(debug, once, delay, min_quality, budget))

    executor_thread = threading.Thread(target=run_loop)
    executor_thread.start()
    return True

def stop_executor_loop():
    global executor_stop
    executor_stop = True
    return True

def is_executor_running():
    return executor_thread is not None and executor_thread.is_alive()

async def executor_loop(debug=False, once=False, delay=30, min_quality=7, budget=250):
    global executor_stop
    while not executor_stop:
        try:
            print("[AutoExecutor] 🔎 סריקה חיה...")
            if get_open_trades_count() >= MAX_OPEN_TRADES:
                print("🔒 יש כבר 4 טריידים פתוחים – דילוג.")
                await asyncio.sleep(delay)
                continue

            results = await scan_all(
                symbols=[],
                market_type="futures",
                interval="15m",
                min_quality=min_quality,
                top=3
            )
            for trade in results:
                if trade["quality_score"] >= min_quality:
                    price = get_live_price(trade["symbol"])
                    sltp = predict_optimal_sl_tp(trade["direction"], price)
                    if price and price > 0:
                        result = execute_trade_live(
                            symbol=trade["symbol"],
                            entry=price,
                            stop=sltp["sl"],
                            tp=sltp["tp"],
                            direction=trade["direction"],
                            leverage=20,
                            budget_usd=budget,
                            market_type=trade.get("market", "futures")
                        )
                        if debug:
                            print("[Debug] Executed:", result)
                        await asyncio.sleep(2)

                if once:
                    executor_stop = True
                    break
        except Exception as e:
            print(f"[AutoExecutor] ❌ שגיאה: {e}")
        if once:
            break
        await asyncio.sleep(delay)

















































