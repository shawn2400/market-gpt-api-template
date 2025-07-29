# auto_executor.py

import asyncio
import logging
from utils.get_live_price import get_price
from utils.trade_storage import save_trade
from utils.quality_score import compute_quality_score
from utils.snapshot_utils import save_trade_snapshot
from utils.pnl_tracker import update_pnl
from scanner_utils import scan_all_futures
from utils.ai_analysis import predict_optimal_sl_tp
from utils.binance_trader import place_futures_order

_executor_task = None  # ניהול מצב הלולאה

async def run_executor(debug=False, once=False, delay=60, min_quality=6, max_budget=100):
    """
    לולאת סריקה חיה עם ביצוע טריידים אוטומטיים בפועל
    """
    global _executor_task

    while True:
        try:
            print(f"\n[AUTO_EXECUTOR] 🚀 סורק את שוק הפיוצ'רס...")
            trades = await scan_all_futures()

            filtered = [t for t in trades if t.get("quality_score", 0) >= min_quality]
            if not filtered:
                print(f"[AUTO_EXECUTOR] ⚠️ לא נמצאו טריידים איכותיים.")
                if once:
                    return
                await asyncio.sleep(delay)
                continue

            trade = filtered[0]
            symbol = trade["symbol"]
            direction = trade["direction"]
            leverage = 10
            entry = float(await get_price(symbol))

            # חיזוי SL/TP עם GPT
            sltp = predict_optimal_sl_tp(symbol, entry, direction)
            stop = sltp["sl"]
            tp = sltp["tp"]
            qty = round((max_budget * leverage) / entry, 3)

            print(f"[AUTO_EXECUTOR] 📊 טרייד: {symbol} | {direction} @ {entry} | SL={stop} TP={tp} Qty={qty} QS={trade['quality_score']}")

            if debug:
                print("[DEBUG] מצב בדיקה - פקודה לא נשלחת ל-Binance.")
            else:
                order = await place_futures_order(
                    symbol=symbol,
                    side="BUY" if direction == "LONG" else "SELL",
                    quantity=qty,
                    entry_price=entry,
                    stop_loss=stop,
                    take_profit=tp,
                    leverage=leverage
                )

                timestamp = str(order.get("timestamp", int(asyncio.get_running_loop().time())))
                pnl = float(order.get("pnl", 0))

                snapshot_path = save_trade_snapshot({
                    "symbol": symbol,
                    "entry": entry,
                    "stop": stop,
                    "tp": tp,
                    "direction": direction,
                    "price_now": entry,
                    "budget": max_budget,
                    "leverage": leverage
                })

                save_trade({
                    "symbol": symbol,
                    "entry": entry,
                    "stop": stop,
                    "tp": tp,
                    "direction": direction,
                    "quantity": qty,
                    "timestamp": timestamp,
                    "quality_score": trade.get("quality_score", 0),
                    "snapshot": snapshot_path
                })

                update_pnl(symbol, pnl, trade.get("quality_score", 0))

                print(f"[AUTO_EXECUTOR] ✅ טרייד בוצע ונשמר: {symbol} {direction} @ {entry}")

        except Exception as e:
            print(f"❌ [AUTO_EXECUTOR] שגיאה כללית: {type(e).__name__} – {e}")

        if once:
            print("[AUTO_EXECUTOR] 🛑 מצב once – סיום.")
            break

        print(f"[AUTO_EXECUTOR] ⏳ ממתין {delay} שניות לסריקה נוספת...")
        await asyncio.sleep(delay)


# === שליטה חיצונית דרך FastAPI ===

def start_executor_loop(debug=False, delay=60, min_quality=6, max_budget=100):
    """
    מפעיל את הלולאה ברקע אם אינה פועלת כבר
    """
    global _executor_task
    if _executor_task is None or _executor_task.done():
        _executor_task = asyncio.create_task(run_executor(
            debug=debug,
            once=False,
            delay=delay,
            min_quality=min_quality,
            max_budget=max_budget
        ))
        print("[AUTO_EXECUTOR] ✅ הופעלה לולאה חיה")
    else:
        print("[AUTO_EXECUTOR] כבר רץ")

def stop_executor_loop():
    """
    מפסיק את הלולאה אם פועלת
    """
    global _executor_task
    if _executor_task and not _executor_task.done():
        _executor_task.cancel()
        print("[AUTO_EXECUTOR] ❌ הופסקה לולאת הסריקה")
    else:
        print("[AUTO_EXECUTOR] לא פעיל כרגע")

def is_executor_running() -> bool:
    """
    מחזיר האם הלולאה פועלת כרגע
    """
    return _executor_task is not None and not _executor_task.done()



















