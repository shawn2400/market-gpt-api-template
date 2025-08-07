import os
import asyncio
import logging
import threading
from dotenv import load_dotenv
from utils.watchlist_utils import load_watchlist
from utils.multi_tf_scanner import multi_tf_scan_with_ai
from utils.trade_executor import execute_trade_live
from utils.ai_analysis import predict_optimal_sl_tp

# === הגדרות סביבתיות ===
load_dotenv()
AUTO_RUN = os.getenv("AUTO_RUN", "false").lower() == "true"
SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", 60))
MIN_QUALITY_SCORE = int(os.getenv("MIN_QUALITY_SCORE", 6))
MAX_TRADE_BUDGET = float(os.getenv("MAX_TRADE_BUDGET", 100))

# === מצב הרצה ===
running = False

# === לולאת אקזקיוטר ===
async def executor_loop():
    global running
    running = True
    logging.info("[AUTO] 🚀 Auto Executor התחיל לרוץ...")

    while running:
        try:
            watchlist = load_watchlist()
            symbols = [s["symbol"] for s in watchlist if s["quality_score"] >= MIN_QUALITY_SCORE]

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
                entry = trade["entry"]
                direction = trade["main_direction"].upper()

                sl_tp = await predict_optimal_sl_tp(entry_price=entry, direction=direction, symbol=symbol)

                if "error" in sl_tp:
                    logging.warning(f"[AUTO] ❌ חיזוי SL/TP נכשל עבור {symbol}: {sl_tp['error']}")
                    continue

                stop = sl_tp["sl"]
                tp = sl_tp["tp"]

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

        except Exception as e:
            logging.error(f"[AUTO] שגיאה בלולאת ביצוע: {e}")

        await asyncio.sleep(SCAN_INTERVAL)

# === הרצה ברקע ===
def start_executor_loop():
    thread = threading.Thread(target=lambda: asyncio.run(executor_loop()), daemon=True)
    thread.start()

def stop_executor_loop():
    global running
    running = False

def is_executor_running():
    return running




























































