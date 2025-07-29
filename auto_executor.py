import asyncio
from binance_client import place_futures_order
from utils.get_live_price import get_price
from utils.trade_storage import save_trade
from utils.quality_score import compute_quality_score
from utils.snapshot_utils import generate_trade_snapshot
from utils.pnl_tracker import update_pnl
from scanner_utils import scan_all_futures

async def start_auto_executor(delay=60, min_quality=6, max_budget=100):
    while True:
        try:
            print(f"[AUTO_EXECUTOR] Scanning market...")
            trades = await scan_all_futures()

            # סינון לפי quality
            filtered = [t for t in trades if t.get("quality_score", 0) >= min_quality]
            if not filtered:
                print(f"[AUTO_EXECUTOR] No high-quality trades found.")
                await asyncio.sleep(delay)
                continue

            trade = filtered[0]  # תיקח את הראשון
            symbol = trade["symbol"]
            direction = trade["signal"]
            leverage = 10
            entry = float(await get_price(symbol))
            stop = entry * 0.985 if direction == "LONG" else entry * 1.015
            tp = entry * 1.02 if direction == "LONG" else entry * 0.98
            qty = round((max_budget * leverage) / entry, 3)

            print(f"[AUTO_EXECUTOR] Executing {direction} on {symbol} entry={entry}")

            order = await place_futures_order(
                symbol=symbol,
                side="BUY" if direction == "LONG" else "SELL",
                quantity=qty,
                entry_price=entry,
                stop_loss=stop,
                take_profit=tp,
                leverage=leverage
            )

            snapshot_path = generate_trade_snapshot(symbol, entry, stop, tp, direction)
            save_trade({
                "symbol": symbol,
                "entry": entry,
                "stop": stop,
                "tp": tp,
                "direction": direction,
                "quantity": qty,
                "timestamp": str(order["timestamp"]),
                "quality_score": trade["quality_score"]
            })
            update_pnl(symbol, float(order.get("pnl", 0)), trade["quality_score"])

        except Exception as e:
            print(f"❌ [AUTO_EXECUTOR] Error: {e}")

        await asyncio.sleep(delay)








