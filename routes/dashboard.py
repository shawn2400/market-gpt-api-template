# routes/dashboard.py
from fastapi import APIRouter
import time

from utils.ws_fallback import LAST_PRICE_CACHE
from utils.watchlist_utils import load_watchlist

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/", summary="Dashboard snapshot")
async def dashboard_snapshot():
    """
    מחזיר Snapshot כללי לדשבורד:
    - Watchlist
    - מחירים אחרונים (WS)
    """
    now = time.time()

    # --- Load watchlist
    watchlist = load_watchlist()

    # --- Last prices snapshot
    last_prices = []
    for sym, info in LAST_PRICE_CACHE.items():
        ts = info.get("ts", 0)
        age_sec = round(now - ts, 2) if ts else None
        last_prices.append({
            "symbol": sym,
            "price": info.get("price"),
            "ts": ts,
            "age_sec": age_sec,
            "fresh": age_sec is not None and age_sec <= 10
        })

    return {
        "ok": True,
        "watchlist": watchlist,
        "last_prices": last_prices,
        "count_symbols": len(last_prices),
        "ts": now
    }










