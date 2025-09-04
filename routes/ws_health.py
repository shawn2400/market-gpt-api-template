# routes/ws_health.py
# ===================
from fastapi import APIRouter, Query
import time
from utils.ws_fallback import get_price, is_price_fresh, LAST_PRICE_CACHE

router = APIRouter(prefix="/ws", tags=["WS Health"])

@router.get("/health", summary="WebSocket price health")
async def ws_health(symbol: str = Query("BTCUSDT", description="סימבול לבדיקה")):
    price = get_price(symbol)
    fresh = is_price_fresh(symbol, max_age_sec=10)
    now = time.time()

    snapshot = []
    for sym, info in LAST_PRICE_CACHE.items():
        ts = info.get("ts", 0)
        age_sec = round(now - ts, 2) if ts else None
        snapshot.append({
            "symbol": sym,
            "price": info.get("price"),
            "ts": ts,
            "age_sec": age_sec,
            "fresh": age_sec is not None and age_sec <= 10
        })

    return {
        "ok": fresh,
        "symbol": symbol,
        "price": price,
        "fresh": fresh,
        "snapshot": snapshot
    }

@router.get("/last-prices", summary="Snapshot of all last prices")
async def ws_last_prices():
    now = time.time()
    snapshot = []
    for sym, info in LAST_PRICE_CACHE.items():
        ts = info.get("ts", 0)
        age_sec = round(now - ts, 2) if ts else None
        snapshot.append({
            "symbol": sym,
            "price": info.get("price"),
            "ts": ts,
            "age_sec": age_sec,
            "fresh": age_sec is not None and age_sec <= 10
        })

    return {"ok": True, "items": snapshot}


