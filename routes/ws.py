# routes/ws.py
from fastapi import APIRouter, Query
from datetime import datetime, timezone
import logging

from utils.ws_fallback import LAST_PRICE_CACHE, update_price
from utils.binance_client import futures_mark_price

router = APIRouter()
logger = logging.getLogger("algogpt")

STALE_THRESHOLD = 10  # שניות

@router.get("/status", tags=["Websocket"])
async def ws_status():
    """
    בדיקת סטטוס עדכניות מחירים מ-WS
    """
    now = datetime.now(timezone.utc).timestamp()
    stale = []

    for symbol, info in LAST_PRICE_CACHE.items():
        last_update = info.get("ts", 0)
        age = now - last_update
        if age > STALE_THRESHOLD:
            stale.append({
                "symbol": symbol,
                "last_update_sec": last_update,
                "age_sec": round(age, 2),
            })
            logger.warning(f"[WS-STALE] {symbol} price not fresh ({age:.1f}s old)")

    return {
        "ok": True,
        "stale": stale,
        "last_checked": datetime.now(timezone.utc).isoformat()
    }

# ✅ NEW: endpoint לעדכון מחיר ידני או מה-Binance
@router.post("/update-price", tags=["Websocket"])
async def update_price_api(symbol: str = Query(..., example="BTCUSDT")):
    """
    מושך Mark Price מ-Binance ושומר אותו ב-cache
    """
    try:
        price = futures_mark_price(symbol)
        update_price(symbol, price)
        return {
            "ok": True,
            "symbol": symbol.upper(),
            "price": price,
            "msg": "Price updated in cache"
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}

