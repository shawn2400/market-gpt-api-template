import asyncio
import argparse
from utils.get_live_price import get_price
from utils.trade_storage import save_trade
from utils.quality_score import compute_quality_score
from utils.snapshot_utils import save_trade_snapshot
from utils.pnl_tracker import update_pnl
from scanner_utils import scan_all_futures
from utils.ai_analysis import predict_optimal_sl_tp
from utils.binance_trader import place_futures_order


async def run_executor(debug=False, once=False, delay=60, min_quality=6, max_budget=100):
    while True:
        try:
            print(f"\n[AUTO_EXECUTOR] 🚀 סורק את שוק הפיוצ'רס...")
            trades = await scan_all_futures()

            filtered = [t for t in trades if t.get("quality_score", 0) >= min_quality]
            if not filtered:
                print(f"[AUTO_EXECUTOR] ⚠️ לא נמצאו טריידים איכותיים.")
                if once:
                    print("[AUTO_EXECUTOR] מצב once - יציאה.")
                    return
                await asyncio.sleep(delay)
                continue

            trade = filtered[0]
            symbol = trade["symbol"]
            direction = trade["signal"]
            leverage = 10
            entry = float(await get_price(symbol))

            # חיזוי SL/TP לפי AI
            sltp = predict_optimal_sl_tp(symbol, entry, direction)
            stop = sltp["sl"]
            tp = sltp["tp"]
            qty = round((max_budget * leverage) / entry, 3)

            print(f"[AUTO_EXECUTOR] 📊 טרייד: {symbol} | {direction} @ {entry} | SL={stop} TP={tp} Qty={qty} QS={trade['quality_score']}")

            if debug:
                print("[DEBUG] מצב בדיקה פעיל - לא נשלחת פקודה ל-Binance.")
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

                # יצירת snapshot
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

                # שמירת הטרייד
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

                # עדכון PNL
                update_pnl(symbol, pnl, trade.get("quality_score", 0))

                print(f"[AUTO_EXECUTOR] ✅ טרייד בוצע ונשמר: {symbol} {direction} @ {entry}")

        except Exception as e:
            print(f"❌ [AUTO_EXECUTOR] שגיאה כללית: {e}")

        if once:
            print("[AUTO_EXECUTOR] 🛑 הרצה בודדת הושלמה. יציאה.")
            break

        print(f"[AUTO_EXECUTOR] ⏳ ממתין {delay} שניות לפני סריקה נוספת...")
        await asyncio.sleep(delay)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="הרצה חיה של AlgoGPT Auto Executor")
    parser.add_argument("--debug", action="store_true", help="מצב בדיקה - ללא שליחה ל־Binance")
    parser.add_argument("--once", action="store_true", help="הרצה חד פעמית בלבד")
    parser.add_argument("--delay", type=int, default=60, help="השהיה בין הרצות (שניות)")
    parser.add_argument("--min_quality", type=int, default=6, help="סף מינימלי לציון איכות")
    parser.add_argument("--budget", type=float, default=100, help="תקציב לטרייד (USDT)")
    args = parser.parse_args()

    asyncio.run(run_executor(
        debug=args.debug,
        once=args.once,
        delay=args.delay,
        min_quality=args.min_quality,
        max_budget=args.budget
    ))



