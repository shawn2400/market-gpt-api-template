# auto_executor.py — גרסה מתוקנת מלאה עם תמיכה בלולאת Thread

import os, asyncio, random
from datetime import datetime
from threading import Thread

from utils.get_live_price import get_price
from utils.trade_storage import save_trade, get_open_trades, save_scanned_trade
from snapshot_utils import save_trade_snapshot
from utils.pnl_tracker import update_pnl
from utils.scanner_utils import scan_all, get_symbols
from utils.ai_analysis import predict_optimal_sl_tp
from utils.watchlist_utils import add_to_watchlist

# תצורה מה־.env
START_MIN_QUALITY = int(os.getenv("MIN_QUALITY_SCORE", 7))
MIN_MIN_QUALITY = 4
MAX_MIN_QUALITY = 10
SCAN_DELAY = int(os.getenv("SCAN_INTERVAL", 7))
MIN_VOLUME = int(os.getenv("MIN_VOLUME", 1_000_000))
ROTATE_SYMBOLS = True
TOP_SYMBOLS = 60
VIP_WATCHLIST_FRAMES = 2
TRENDING_ONLY = os.getenv("TRENDING_ONLY", "false").lower() == "true"

_executor_task: asyncio.Task | None = None

def smart_batch(symbols: list[str], size: int):
    random.shuffle(symbols)
    for i in range(0, len(symbols), size):
        yield symbols[i:i+size]

async def run_executor(
    debug=False,
    once=False,
    delay=SCAN_DELAY,
    min_quality=START_MIN_QUALITY,
    max_budget=100
):
    fail_count = 0
    min_q = min_quality

    while True:
        try:
            print(f"\n[AUTO_EXECUTOR] 🚀 scanning… min_quality={min_q}")
            syms = get_symbols("futures", MIN_VOLUME, TRENDING_ONLY)
            batch = (
                random.choice(list(smart_batch(syms, TOP_SYMBOLS)))
                if ROTATE_SYMBOLS and len(syms) > TOP_SYMBOLS else syms[:TOP_SYMBOLS]
            )

            trades = await scan_all(
                market_type="futures",
                interval="1m",
                limit=len(batch),
                min_quality=min_q,
                trending_only=TRENDING_ONLY,
                min_volume=MIN_VOLUME
            )
            for t in trades:
                t["scanned_at"] = datetime.utcnow().isoformat()
                save_scanned_trade(t)

            # דינמיקת סף איכות
            if not trades:
                fail_count += 1
                if fail_count >= 2 and min_q > MIN_MIN_QUALITY:
                    min_q -= 1
                    fail_count = 0
                    print(f"[DYN QS] lower threshold → {min_q}")
            else:
                if len(trades) > 5 and min_q < MAX_MIN_QUALITY:
                    min_q += 1
                    print(f"[DYN QS] raise threshold → {min_q}")
                fail_count = 0

                # ביצוע טרייד
                trades.sort(key=lambda x: (x["quality_score"], x["volume"]), reverse=True)
                for tr in trades:
                    sym, dir_ = tr["symbol"], tr["direction"]
                    if any(t["symbol"] == sym and t["direction"] == dir_ for t in get_open_trades()):
                        continue
                    if len(tr.get("frames", [])) >= VIP_WATCHLIST_FRAMES:
                        add_to_watchlist(sym, dir_, tr["quality_score"], reason=f"frames:{tr['frames']}")

                    price = await asyncio.to_thread(get_price, sym)
                    sltp = predict_optimal_sl_tp(sym, price, dir_)
                    qty = round((max_budget * 10) / price, 3)
                    print(f"[TRADE] {sym} {dir_}@{price} SL={sltp['sl']} TP={sltp['tp']} Q={qty}")

                    if not debug:
                        from utils.binance_trader import place_futures_order
                        order = await place_futures_order(
                            symbol=sym,
                            side="BUY" if dir_ == "LONG" else "SELL",
                            quantity=qty,
                            entry_price=price,
                            stop_loss=sltp["sl"],
                            take_profit=sltp["tp"],
                            leverage=10
                        )
                        snapshot = save_trade_snapshot({
                            "symbol": sym,
                            "entry": price,
                            "stop": sltp["sl"],
                            "tp": sltp["tp"],
                            "direction": dir_,
                            "price_now": price,
                            "budget": max_budget,
                            "leverage": 10,
                            "quality_score": tr["quality_score"]
                        })
                        save_trade({
                            "symbol": sym,
                            "entry": price,
                            "stop": sltp["sl"],
                            "tp": sltp["tp"],
                            "direction": dir_,
                            "quantity": qty,
                            "timestamp": order.get("timestamp"),
                            "quality_score": tr["quality_score"],
                            "snapshot": snapshot
                        })
                        update_pnl(sym, dir_, price, price, 10, qty)
                        print(f"[✅ EXECUTED] {sym}")
                    break

        except Exception as e:
            print(f"[AUTO_EXECUTOR] ERROR: {e}")

        if once:
            break

        await asyncio.sleep(delay)

# === START / STOP LOOP ===

def start_executor_loop(debug=False, delay=SCAN_DELAY, min_quality=START_MIN_QUALITY, max_budget=100):
    def runner():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(run_executor(debug, False, delay, min_quality, max_budget))

    t = Thread(target=runner, daemon=True)
    t.start()
    print("[AUTO_EXECUTOR] ✅ הופעלה לולאה חיה")

def stop_executor_loop():
    global _executor_task
    if _executor_task and not _executor_task.done():
        _executor_task.cancel()
        print("[AUTO_EXECUTOR] ❌ הופסקה")
    else:
        print("[AUTO_EXECUTOR] לא רצה")

def is_executor_running() -> bool:
    return bool(_executor_task and not _executor_task.done())






































