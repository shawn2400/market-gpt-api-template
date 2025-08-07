# auto_executor.py

import threading
import asyncio
import os
import time
import logging

from utils.scanner_utils import scan_all
from utils.ws_fallback import get_price, is_price_fresh
from utils.trade_executor import execute_trade_live
from utils.pnl_tracker import update_pnl
from utils.trade_storage import get_open_trades_count
from utils.watchlist_utils import load_watchlist
from utils.ai_analysis import predict_optimal_sl_tp

executor_thread = None
executor_stop = False
executor_lock = threading.Lock()
MAX_OPEN_TRADES = 4

AUTO_RUN = os.getenv("AUTO_RUN", "false").lower() == "true"
SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", 60))
MIN_QUALITY_SCORE = int(os.getenv("MIN_QUALITY_SCORE", 6))
MAX_TRADE_BUDGET = float(os.getenv("MAX_TRADE_BUDGET", 100))
PRICE_MAX_AGE = int(os.getenv("PRICE_MAX_AGE", 10))

def start_executor_loop(debug=False, once=False, delay=None, min_quality=None, budget=None):
    global executor_thread, executor_stop

    with executor_lock:
        if executor_thread and executor_thread.is_alive():
            logging.info("[AutoExecutor] כבר רץ תהליך קיים – דילוג.")
            return False

        executor_stop = False
        delay = delay or SCAN_INTERVAL
        min_quality = min_quality or MIN_QUALITY_SCORE
        budget = budget or MAX_TRADE_BUDGET

        def run_loop():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(executor_loop(debug, once, delay, min_quality, budget))

        executor_thread = threading.Thread(target=run_loop, name="AutoExecutorThread")
        executor_thread.start()
        return True

def stop_executor_loop():
    global executor_stop
    executor_stop = True
    return True

def is_executor_running():
    return executor_thread is not None and executor_thread.is_alive()

async def executor_loop(debug=False, once=False, delay=60, min_quality=6, budget=100):
    global executor_stop

    while not executor_stop:
        try:
            logging.info("[AutoExecutor] 🔍 סריקה חיה התחילה...")

            if get_open_trades_count() >= MAX_OPEN_TRADES:
                logging.info("🔒 יש כבר 4 טריידים פתוחים – דילוג.")
                await asyncio.sleep(delay)
                continue

            watchlist = load_watchlist()
            symbols = [x["symbol"] for x in watchlist if "symbol" in x]
            if not symbols:
                logging.warning("[AutoExecutor] ⚠️ אין סמלים ברשימת המעקב.")
                await asyncio.sleep(delay)
                continue

            results = await scan_all(
                symbols=symbols,
                interval="15m",
                min_quality=min_quality,
                top=3
            )

            for trade in results:
                if trade["quality_score"] < min_quality:
                    continue

                symbol = trade["symbol"]

                if not is_price_fresh(symbol, max_age_sec=PRICE_MAX_AGE):
                    logging.warning(f"[AutoExecutor] ⚠️ מחיר {symbol} לא עדכני (> {PRICE_MAX_AGE}s) – דילוג.")
                    continue

                price = await get_price(symbol)
                if not price or price <= 0:
                    logging.warning(f"[AutoExecutor] ⚠️ מחיר לא תקין עבור {symbol}")
                    continue

                direction = trade["direction"]
                sltp = predict_optimal_sl_tp(direction, price)
                sl = sltp["sl"]
                tp = sltp["tp"]

                logging.info(f"[AutoExecutor] 🎯 טרייד נבחר: {symbol} | כיוון: {direction} | איכות: {trade['quality_score']} | מחיר: {price} | SL: {sl} | TP: {tp}")

                if not debug:
                    result = execute_trade_live(
                        symbol=symbol,
                        entry=price,
                        stop=sl,
                        tp=tp,
                        direction=direction,
                        leverage=20,
                        budget_usd=budget,
                        market_type=trade.get("market", "futures"),
                    )
                    logging.info(f"[AutoExecutor] ✅ טרייד נשלח: {result}")
                else:
                    logging.info("[AutoExecutor] [DEBUG] מצב בדיקה – טרייד לא נשלח בפועל")

                await asyncio.sleep(2)

                if once:
                    executor_stop = True
                    break

        except Exception as e:
            logging.exception(f"[AutoExecutor] ❌ שגיאה כללית: {e}")

        if once:
            break
        await asyncio.sleep(delay)



























































