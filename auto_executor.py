# auto_executor.py

import os
import asyncio
import logging
from dotenv import load_dotenv

from utils.scan_futures import scan_all as scan_all_futures  # ✅ תיקון שם הפונקציה
from utils.get_live_price import get_live_price
from utils.quantity_utils import auto_risk_allocation
from utils.calculate_quantity import get_step_size
from snapshot_utils import save_trade_snapshot
from utils.pnl_tracker import update_pnl
from utils.ai_analysis import predict_optimal_sl_tp
from utils.binance_client import client

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

AUTO_RUN = os.getenv("AUTO_RUN", "false").lower() == "true"
MIN_QUALITY = int(os.getenv("MIN_QUALITY_SCORE", 6))
MAX_BUDGET = float(os.getenv("MAX_TRADE_BUDGET", 100))


async def auto_execute_trade():
    logging.info("🚀 סריקה חיה התחילה...")
    results = await scan_all_futures()
    good_trades = [t for t in results if t["quality_score"] >= MIN_QUALITY]

    if not good_trades:
        logging.info("❌ לא נמצאו טריידים מתאימים.")
        return

    # בחר טרייד הכי איכותי
    trade = sorted(good_trades, key=lambda x: x["quality_score"], reverse=True)[0]
    symbol = trade["symbol"]
    direction = trade["direction"]
    entry_price = get_live_price(symbol)
    leverage = trade.get("leverage", 5)

    # חיזוי SL/TP
    sltp = predict_optimal_sl_tp(symbol, direction, entry_price)
    stop_price = sltp["stop"]
    tp_price = sltp["tp"]

    # חישוב תקציב וכמות
    risk_allocation = auto_risk_allocation(entry_price, stop_price, total_budget=MAX_BUDGET, risk_percent=2)
    step = get_step_size(symbol)
    raw_qty = (risk_allocation * leverage) / entry_price
    qty = (int(raw_qty / step)) * step
    qty = round(qty, 6)

    if qty <= 0:
        logging.warning("⚠️ כמות לא חוקית. דילוג.")
        return

    try:
        # ביצוע פקודת שוק
        client.futures_create_order(
            symbol=symbol,
            side="BUY" if direction == "LONG" else "SELL",
            type="MARKET",
            quantity=qty
        )
        logging.info(f"✅ בוצע טרייד: {symbol} {direction} Qty: {qty}")

        # שליחת SL
        client.futures_create_order(
            symbol=symbol,
            side="SELL" if direction == "LONG" else "BUY",
            type="STOP_MARKET",
            stopPrice=stop_price,
            quantity=qty,
            timeInForce="GTC"
        )

        # שליחת TP
        client.futures_create_order(
            symbol=symbol,
            side="SELL" if direction == "LONG" else "BUY",
            type="TAKE_PROFIT_MARKET",
            stopPrice=tp_price,
            quantity=qty,
            timeInForce="GTC"
        )

        # צילום Snapshot
        snapshot_path = save_trade_snapshot(symbol, direction, entry_price, stop_price, tp_price)

        # עדכון ל־PNL Tracker
        update_pnl(symbol, direction, entry_price, tp_price, leverage, qty)

        logging.info(f"📍 SL/TP נשלחו: SL={stop_price}, TP={tp_price}")
        logging.info(f"📸 Snapshot נשמר: {snapshot_path}")

    except Exception as e:
        logging.error(f"[!] שגיאה בביצוע אוטומטי: {e}")


if __name__ == "__main__":
    if AUTO_RUN:
        asyncio.run(auto_execute_trade())
    else:
        logging.info("AUTO_RUN מוגדר ל־false, לא מתבצעת פעולה.")

















