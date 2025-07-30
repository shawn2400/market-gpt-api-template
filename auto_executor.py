# auto_executor.py — גרסה עדכנית

import asyncio, os, random
from utils.get_live_price import get_price
from utils.trade_storage import save_trade, get_open_trades, save_scanned_trade
from utils.quality_score import compute_quality_score
from snapshot_utils import save_trade_snapshot
from utils.pnl_tracker import update_pnl
from utils.scanner_utils import scan_all, get_symbols
from utils.ai_analysis import predict_optimal_sl_tp
from utils.watchlist_utils import add_to_watchlist

# הגדרות דינמיות
START_MIN_QUALITY = int(os.getenv("MIN_QUALITY_SCORE",7))
MIN_MIN_QUALITY   = 4
MAX_MIN_QUALITY   = 10
SCAN_DELAY        = int(os.getenv("SCAN_INTERVAL",7))
MIN_VOLUME        = int(os.getenv("MIN_VOLUME",1000000))
ROTATE_SYMBOLS    = True
TOP_SYMBOLS       = 60
VIP_WATCHLIST_FRAMES = 2
TRENDING_ONLY     = os.getenv("TRENDING_ONLY","false").lower()=="true"

def smart_batch(symbols, batch_size):
    random.shuffle(symbols)
    for i in range(0, len(symbols), batch_size):
        yield symbols[i:i+batch_size]

_executor_task = None

async def run_executor(debug=False, once=False, delay=SCAN_DELAY, min_quality=START_MIN_QUALITY, max_budget=100):
    global _executor_task
    fail_count = 0
    min_q = min_quality

    while True:
        try:
            print(f"\n[AUTO_EXECUTOR] 🚀 סורק... min_quality={min_q}")
            all_syms = get_symbols("futures", MIN_VOLUME, TRENDING_ONLY)
            if ROTATE_SYMBOLS and len(all_syms)>TOP_SYMBOLS:
                sym = random.choice(list(smart_batch(all_syms,TOP_SYMBOLS)))
            else:
                sym = all_syms[:TOP_SYMBOLS]

            trades = await scan_all(
                market_type="futures",
                interval="1m",
                limit=len(sym),
                min_quality=min_q,
                trending_only=TRENDING_ONLY,
                min_volume=MIN_VOLUME
            )

            for t in trades:
                from datetime import datetime
                t["scanned_at"]=datetime.utcnow().isoformat()
                save_scanned_trade(t)

            if not trades:
                fail_count+=1
                if fail_count>=2 and min_q>MIN_MIN_QUALITY:
                    min_q-=1; fail_count=0
                    print(f"[DYNAMIC QS] מוריד סף ל־{min_q}")
                if once: break
                await asyncio.sleep(delay)
                continue
            else:
                if len(trades)>5 and min_q<MAX_MIN_QUALITY:
                    min_q+=1
                    print(f"[DYNAMIC QS] מעלה סף ל־{min_q}")
                fail_count=0

            trades.sort(key=lambda x:(x["quality_score"],x["volume"]),reverse=True)
            for tr in trades:
                symb=tr["symbol"]; dirc=tr["direction"]
                open_t=get_open_trades()
                if any(t["symbol"]==symb and t["direction"]==dirc and t.get("status")=="OPEN" for t in open_t):
                    continue
                if "frames" in tr and len(tr["frames"])>=VIP_WATCHLIST_FRAMES:
                    add_to_watchlist(symb, dirc, tr["quality_score"], reason=f"Confluence:{tr['frames']}")
                lvl=10; price=float(await get_price(symb))
                sltp=predict_optimal_sl_tp(symb, price, dirc)
                stop, tp = sltp["sl"], sltp["tp"]
                qty=round((max_budget*lvl)/price,3)

                print(f"[AUTO_EXECUTOR] 📊 {symb} {dirc}@{price} SL={stop} TP={tp} Q={qty}")
                if debug: continue

                from utils.binance_trader import place_futures_order
                order=await place_futures_order(symb, "BUY" if dirc=="LONG" else "SELL", qty, price, stop, tp, lvl)
                ts=str(order.get("timestamp",int(asyncio.get_running_loop().time())))
                save_trade({
                    "symbol":symb,"entry":price,"stop":stop,"tp":tp,
                    "direction":dirc,"quantity":qty,"timestamp":ts,
                    "quality_score":tr["quality_score"],
                    "snapshot": save_trade_snapshot({"symbol":symb,"entry":price,"stop":stop,"tp":tp,"direction":dirc,"price_now":price,"budget":max_budget,"leverage":lvl,"quality_score":tr["quality_score"]})
                })
                update_pnl(symb,dirc,price,price,lvl,qty)
                print(f"[AUTO_EXECUTOR] ✅ {symb} {dirc} done")
                break

        except Exception as e:
            print(f"❌ [AUTO_EXECUTOR] {e}")

        if once: break
        await asyncio.sleep(delay)

def start_executor_loop(debug=False, delay=SCAN_DELAY, min_quality=START_MIN_QUALITY, max_budget=100):
    global _executor_task
    try:
        loop = asyncio.get_running_loop()
    except:
        loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)

    if _executor_task is None or _executor_task.done():
        _executor_task = loop.create_task(run_executor(debug, False, delay, min_quality, max_budget))
        print("[AUTO_EXECUTOR] ✅ מופעל")
    else:
        print("[AUTO_EXECUTOR] כבר רץ")

def stop_executor_loop():
    global _executor_task
    if _executor_task and not _executor_task.done():
        _executor_task.cancel()
        print("[AUTO_EXECUTOR] ❌ נעצר")
    else:
        print("[AUTO_EXECUTOR] לא רץ")

def is_executor_running() -> bool:
    return _executor_task is not None and not _executor_task.done()




































