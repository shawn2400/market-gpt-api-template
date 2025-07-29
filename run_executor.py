import asyncio
import argparse
from utils.get_live_price import get_price
from utils.trade_storage import save_trade
from utils.quality_score import compute_quality_score
from utils.snapshot_utils import generate_trade_snapshot
from utils.pnl_tracker import update_pnl
from scanner_utils import scan_all_futures
from utils.ai_analysis import predict_optimal_sl_tp  # ✅ AI SL/TP
from utils.binance_client import place_futures_order


async def run_executor(debug=False, once=False, delay=60, min_quality=6, max_budget=100):
    while True:
        try:
            print(f"[AUTO_EXECUTOR] סורק את השוק...")
            trades = await scan_all_futures()

            filtered = [t for t in trades if t.get("quality_score", 0) >= min_quality]
            if not filtered:
                print(f"[AUTO_EXECUTOR] לא נמצאו טריידים איכותיים.")
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

            # ✅ חיזוי SL/TP לפי כיוון ומחיר
            sltp = predict_optimal_sl_tp(symbol, entry, direction)
            stop = sltp["sl"]
            tp = sltp["tp"]
            qty = round((max_budget * leverage) / entry, 3)

            print(f"[AUTO_EXECUTOR] {direction} על {symbol} @ {entry} | SL: {stop}, TP: {tp}, Qty: {qty}, QS: {trade['quality_score']}")

            if debug:
                print("[DEBUG] מצב בדיקה פעיל - לא מתבצע שליחת פקודה ל־Binance")
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

                timestamp = str(order.get("timestamp", asyncio.get_event_loop().time()))
                pnl = float(order.get("pnl", 0))

                snapshot_path = generate_trade_snapshot(symbol, entry, stop, tp, direction)

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

        except Exception as e:
            print(f"❌ [AUTO_EXECUTOR] שגיאה: {e}")

        if once:
            print("[AUTO_EXECUTOR] בוצע טרייד אחד בלבד. סיום.")
            break

        await asyncio.sleep(delay)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--debug", action="store_true", help="הדפס פרטים מבלי לבצע מסחר בפועל")
    parser.add_argument("--once", action="store_true", help="הרץ רק פעם אחת ויצא")
    parser.add_argument("--delay", type=int, default=60, help="השהיה בין סריקות")
    parser.add_argument("--min_quality", type=int, default=6, help="סף מינימום לאיכות הטרייד")
    parser.add_argument("--budget", type=float, default=100, help="תקציב ב-USDT לכל טרייד")
    args = parser.parse_args()

    asyncio.run(run_executor(
        debug=args.debug,
        once=args.once,
        delay=args.delay,
        min_quality=args.min_quality,
        max_budget=args.budget
    ))


