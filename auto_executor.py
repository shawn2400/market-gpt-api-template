import asyncio
from utils.binance_client import place_futures_order
from utils.get_live_price import get_price
from utils.trade_storage import save_trade
from utils.snapshot_utils import generate_trade_snapshot
from utils.pnl_tracker import update_pnl
from scanner_utils import scan_all_futures


async def start_auto_executor(delay=60, min_quality=6, max_budget=100):
    """
    מריץ סריקה כל X שניות, ומבצע טרייד בפועל אם נמצא טרייד איכותי.
    """
    while True:
        try:
            print("[AUTO_EXECUTOR] Scanning market...")
            trades = await scan_all_futures()

            # סינון לפי איכות
            filtered = [t for t in trades if t.get("quality_score", 0) >= min_quality]
            if not filtered:
                print("[AUTO_EXECUTOR] No high-quality trades found.")
                await asyncio.sleep(delay)
                continue

            # בחר את הטרייד הראשון
            trade = filtered[0]
            symbol = trade["symbol"]
            direction = trade["signal"]
            leverage = 10
            entry = float(await get_price(symbol))

            # חישוב SL ו־TP לפי כיוון
            stop = entry * 0.985 if direction == "LONG" else entry * 1.015
            tp = entry * 1.02 if direction == "LONG" else entry * 0.98

            # חישוב כמות לפי תקציב
            qty = round((max_budget * leverage) / entry, 3)

            print(f"[AUTO_EXECUTOR] Executing {direction} on {symbol} at {entry} with qty={qty}")

            # שליחת הוראה ל-Binance
            order = await place_futures_order(
                symbol=symbol,
                side="BUY" if direction == "LONG" else "SELL",
                quantity=qty,
                entry_price=entry,
                stop_loss=stop,
                take_profit=tp,
                leverage=leverage
            )

            # יצירת snapshot גרפי
            generate_trade_snapshot(symbol, entry, stop, tp, direction)

            # שמירת הטרייד
            save_trade({
                "symbol": symbol,
                "entry": entry,
                "stop": stop,
                "tp": tp,
                "direction": direction,
                "quantity": qty,
                "timestamp": order.get("timestamp"),
                "quality_score": trade.get("quality_score", 0)
            })

            # עדכון PNL
            update_pnl(symbol, float(order.get("pnl", 0)), trade.get("quality_score", 0))

        except Exception as e:
            print(f"❌ [AUTO_EXECUTOR] Error: {e}")

        await asyncio.sleep(delay)










