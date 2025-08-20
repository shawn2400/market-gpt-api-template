# routes/ws_health.py
from fastapi import APIRouter, Query
from utils.ws_fallback import get_price, is_price_fresh

router = APIRouter(prefix="/ws", tags=["WS Health"])

@router.get("/health", summary="WebSocket price health")
async def ws_health(symbol: str = Query("BTCUSDT", description="סימבול לבדיקה")):
    price = get_price(symbol)
    fresh = is_price_fresh(symbol, max_age_sec=10)

    return {
        "ok": fresh,
        "symbol": symbol,
        "price": price,
        "fresh": fresh,
    }
