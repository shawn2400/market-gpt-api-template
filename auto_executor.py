# ===== auto_executor.py =====

import asyncio
import os
import logging
import random
from utils.get_live_price import get_price
from utils.trade_storage import save_trade, get_open_trades, save_scanned_trade
from utils.quality_score import compute_quality_score
from snapshot_utils import save_trade_snapshot
from utils.pnl_tracker import update_pnl
from utils.scanner_utils import scan_all, get_symbols  # כאן הייבוא הנכון
from utils.ai_analysis import predict_optimal_sl_tp
from utils.watchlist_utils import add_to_watchlist

# קביעת קבועים מה־env
START_MIN_QUALITY = int(os.getenv("MIN_QUALITY_SCORE", 7))
MIN_MIN_QUALITY = 4
MAX_MIN_QUALITY = 10
SCAN_DELAY = int(os.getenv("SCAN_INTERVAL", 7))
MIN_VOLUME = int(os.getenv("MIN_VOLUME", 1_000_000))
ROTATE_SYMBOLS = True
TOP_SYMBOLS = int(os.getenv("TOP_SYMBOLS", 60))
VIP_WATCHLIST_FRAMES = 2
TRENDING_ONLY = os.getenv("TRENDING_ONLY", "false").lower() == "true"

def smart_batch(symbols, batch_size):
    random.shuffle(symbols)
    for i in range(0, len(symbols), batch_size):
        yield symbols[i:i+batch_size]

_executor_task = None

async def run_executor(debug=False, once=False, delay=SCAN_DELAY, min_quality=START_MIN_QUALITY, max_budget=100):
    global _executor_task

    fail_count = 0
    min_quality_cur = min_quality

    while True:
        try:
            print(f"\n[AUTO_EXECUTOR] 🚀 סורק את שוק הפיוצ'רס... min_quality={min_quality_cur}")
            # Trending + Volume + Smart batching
            all_symbols = get_symbols(
                market_type="futures",
                min_volume=MIN_VOLUME,
                trending_only=TRENDING_ONLY
            )
            if ROTATE_SYMBOLS and len(all_symbols) > TOP_SYMBOLS:
                batches = list(smart_batch(all_symbols, TOP_SYMBOLS))
                symbols_batch = random.choice(batches)
            else:
                symbols_batch = all_symbols[:TOP_SYMBOLS]

            # Scan batch
            trades = await scan_all(
                market_type="futures",
                interval="1m",
                limit=len(symbols_batch),
                min_quality=min_quality_cur,
                trending_only=TRENDING_ONLY,
                min_volume=MIN_VOLUME
            )

            # Save all scanned trades
            for t in trades:
                from datetime import datetime
                t['scanned_at'] = datetime.utcnow().isoformat()
                save_scanned_trade(t)

            # Dynamic quality (אם אין מספיק — מוריד סף; אם יש הרבה — מעלה)
            if not trades or len(trades) == 0:
                fail_count += 1
                if fail_count >= 2 and min_quality_cur > MIN_MIN_QUALITY:
                    min_quality_cur -= 1
                    print(f"[DYNAMIC QS] אין טריידים — מוריד סף איכות ל־{min_quality_cur}")
                    fail_count = 0
                await asyncio.sleep(delay)
                if once:
                    break
                continue
            else:
                if len(trades) > 5 and min_quality_cur < MAX_MIN_QUALITY:
                    min_quality_cur += 1
                    print(f"[DYNAMIC QS] יותר מדי טריידים — מעלה סף איכות ל־{min_quality_cur}")
                fail_count = 0

            # Pick the best trades only (TOP QS + Confluence)
            trades = sorted(trades, key=lambda x: (x.get("quality_score", 0), x.get("volume", 0)), reverse=True)
            for trade in trades:
                symbol = trade["symbol"]
                direction = trade["direction"]
                # Double position prevention
                open_trades = get_open_trades()
                already_open = any(
                    t["symbol"] == symbol and t["direction"] == direction and t.get("status") == "OPEN"
                    for t in open_trades
                )
                if already_open:
                    print(f"[SKIP] פוזיציה פתוחה קיימת ל־{symbol} {direction} — מדלג")
                    continue
                # VIP WATCHLIST — Confluence
                if "frames" in trade and len(trade["frames"]) >= VIP_WATCHLIST_FRAMES:
                    add_to_watchlist(
                        symbol, direction, trade.get("quality_score", 0),
                        reason=f"Confluence: {trade.get('frames', [])}"
                    )
                leverage = 10
                entry = float(await get_price(symbol))
                sltp = predict_optimal_sl_tp(symbol, entry, direction)
                stop = sltp["sl"]
                tp = sltp["tp"]
                qty = round((max_budget * leverage) / entry, 3)
                print(f"[AUTO_EXECUTOR] 📊 טרייד: {symbol} | {direction} @ {entry} | SL={stop} TP={tp} Qty={qty} QS={trade.get('quality_score', 0)}")
                if debug:
                    print("[DEBUG] מצב בדיקה בלבד — לא נשלחת פקודה ל-Binance.")
                    continue
                from utils.binance_trader import place_futures_order
                order = await place_futures_order(
                    symbol=symbol,
                    side="BUY" if direction == "LONG" else "SELL",
                    quantity=qty,
                    entry_price=entry,
                    stop_loss=stop,
                    take_profit=tp,
                    leverage=leverage
                )
                from datetime import datetime
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
                    "leverage": leverage,
                    "quality_score": trade.get("quality_score", 0)
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
                update_pnl(symbol, direction, entry, entry, leverage, qty)
                print(f"[AUTO_EXECUTOR] ✅ טרייד בוצע ונשמר: {symbol} {direction} @ {entry}")
                break

        except Exception as e:
            print(f"❌ [AUTO_EXECUTOR] שגיאה כללית: {type(e).__name__} – {e}")

        if once:
            print("[AUTO_EXECUTOR] מצב once — יציאה.")
            break

        print(f"[AUTO_EXECUTOR] ⏳ ממתין {delay} שניות לסריקה נוספת...")
        await asyncio.sleep(delay)

def start_executor_loop(debug=False, delay=SCAN_DELAY, min_quality=START_MIN_QUALITY, max_budget=100):
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
    global _executor_task
    if _executor_task and not _executor_task.done():
        _executor_task.cancel()
        print("[AUTO_EXECUTOR] ❌ הופסקה לולאת הסריקה")
    else:
        print("[AUTO_EXECUTOR] לא פעיל כרגע")

def is_executor_running() -> bool:
    return _executor_task is not None and not _executor_task.done()






























