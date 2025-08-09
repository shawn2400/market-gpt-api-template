import os
import asyncio
import logging
from dotenv import load_dotenv
from utils.watchlist_utils import load_watchlist
from utils.multi_tf_scanner import multi_tf_scan_with_ai
from utils.trade_executor import execute_trade_live
from utils.ai_analysis import predict_optimal_sl_tp
from utils.ws_fallback import get_price, is_price_fresh

load_dotenv()

SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", 60))
MIN_QUALITY_SCORE = int(os.getenv("MIN_QUALITY_SCORE", 6))
MAX_TRADE_BUDGET = float(os.getenv("MAX_TRADE_BUDGET", 100))

_running = False
_task = None

async def executor_loop():
    global _running
    _running = True
    logging.info("[AUTO] 🚀 Auto Executor התחיל לרוץ...")

    try:
        while _running:
            try:
                watchlist = load_watchlist(min_quality=MIN_QUALITY_SCORE)
                symbols = [entry["symbol"] for entry in watchlist]

                if not symbols:
                    logging.info("[AUTO] ⏳ אין סימבולים עם איכות מספקת בסריקה הנוכחית.")
                    await asyncio.sleep(SCAN_INTERVAL)
                    continue

                logging.info(f"[AUTO] 📊 התחלת סריקה על {len(symbols)} סימבולים...")

                scan_results = await multi_tf_scan_with_ai(
                    timeframes=("15m", "1h"),
                    markets=("futures",),
                    min_quality=MIN_QUALITY_SCORE,
                    top=5,
                    trending_only=False
                )

                for trade in scan_results:
                    symbol = trade["symbol"]
                    direction = trade.get("direction", trade.get("main_direction", "LONG")).upper()

                    entry = await get_price(symbol)
                    if entry is None:
                        logging.warning(f"[AUTO] ⚠️ מחיר לא זמין עבור {symbol}, מדלג.")
                        continue

                    if not is_price_fresh(symbol, max_age_sec=10):
                        logging.warning(f"[AUTO] ⏳ מחיר לא עדכני עבור {symbol}, מדלג.")
                        continue

                    sl_tp = await predict_optimal_sl_tp(entry_price=entry, direction=direction, symbol=symbol)
                    if isinstance(sl_tp, dict) and "error" in sl_tp:
                        logging.warning(f"[AUTO] ❌ חיזוי SL/TP נכשל עבור {symbol}: {sl_tp['error']}")
                        continue

                    stop, tp = sl_tp if isinstance(sl_tp, tuple) else (None, None)
                    if stop is None or tp is None:
                        logging.warning(f"[AUTO] ⚠️ SL/TP לא תקינים עבור {symbol}, מדלג.")
                        continue

                    logging.info(f"[AUTO] 📈 טרייד מומלץ: {symbol} | {direction} | כניסה: {entry} | SL: {stop} | TP: {tp}")

                    result = await execute_trade_live(
                        symbol=symbol,
                        entry=entry,
                        stop=stop,
                        tp=tp,
                        direction=direction,
                        leverage=20,
                        budget_usd=MAX_TRADE_BUDGET,
                        market_type="futures"
                    )

                    logging.info(f"[AUTO] 💸 תוצאה: {result}")

            except asyncio.CancelledError:
                logging.info("[AUTO] 🔴 Auto Executor בוטל.")
                break
            except Exception as e:
                logging.error(f"[AUTO] ❗ שגיאה בלולאת ביצוע: {e}")

            await asyncio.sleep(SCAN_INTERVAL)

    finally:
        _running = False
        logging.info("[AUTO] Auto Executor סיים ריצה.")

def start_executor():
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(executor_loop())
        logging.info("[AUTO] ✅ Auto Executor started")
        return True
    else:
        logging.info("[AUTO] ⚠️ Auto Executor already running")
        return False

def stop_executor():
    global _running, _task
    if _running:
        _running = False
        if _task:
            _task.cancel()
            _task = None
        logging.info("[AUTO] ⏹️ Auto Executor stopped")
        return True
    else:
        logging.info("[AUTO] ⚠️ Auto Executor was not running")
        return False

def is_executor_running():
    return _running

































































