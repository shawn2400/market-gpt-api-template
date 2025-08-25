# routes/price.py
from __future__ import annotations
import asyncio, time, json, logging
from typing import Optional, Dict, Any
from fastapi import APIRouter, Path, HTTPException
from pydantic import BaseModel
from utils.ws_fallback import get_price as get_cached_price, update_price
from utils.binance_client import futures_mark_price  # מחזיר float
try:
    from utils.redis_client import redis_client  # ייתכן שאין / ייתכן sync/async
except Exception:
    redis_client = None  # type: ignore

logger = logging.getLogger("algogpt.price")
router = APIRouter(tags=["Price"])

class PriceResponse(BaseModel):
    ok: bool
    symbol: Optional[str] = None
    price: Optional[float] = None
    source: Optional[str] = None  # redis/cache/binance
    ts: Optional[float] = None
    error: Optional[str] = None

TTL =  int(__import__("os").getenv("PRICE_MAX_AGE_SEC", "10"))

@router.get("/", response_model=PriceResponse, operation_id="getPriceHint")
async def get_price_hint() -> PriceResponse:
    return PriceResponse(ok=True, error='Use /price/{symbol} (e.g., /price/BTCUSDT)')

async def _redis_get(key: str):
    if not redis_client: return None
    try:
        import inspect
        if inspect.iscoroutinefunction(redis_client.get):
            val = await redis_client.get(key)  # type: ignore
        else:
            val = redis_client.get(key)       # type: ignore
        return float(val) if val is not None else None
    except Exception as e:
        logger.warning(f"[PRICE] Redis get failed: {e}")
        return None

async def _redis_set(key: str, value: float, ex: int = 30):
    if not redis_client: return
    try:
        import inspect
        if inspect.iscoroutinefunction(redis_client.set):
            await redis_client.set(key, value, ex=ex)  # type: ignore
        else:
            redis_client.set(key, value, ex=ex)        # type: ignore
    except Exception as e:
        logger.warning(f"[PRICE] Redis set failed: {e}")

@router.get("/{symbol}", response_model=PriceResponse, operation_id="getPriceSymbol")
async def get_price_symbol(symbol: str = Path(..., min_length=3, example="BTCUSDT")) -> PriceResponse:
    sym = symbol.upper().strip()
    # 1) Redis
    val = await _redis_get(f"price:{sym}")
    if val is not None:
        return PriceResponse(ok=True, symbol=sym, price=val, source="redis", ts=time.time())

    # 2) cache מקומי
    local = get_cached_price(sym)
    if local is not None:
        return PriceResponse(ok=True, symbol=sym, price=float(local), source="cache", ts=time.time())

    # 3) Binance (non-blocking via thread)
    try:
        px = await asyncio.to_thread(futures_mark_price, sym)  # מחזיר float
        if px is None or px <= 0:
            raise ValueError("Empty or invalid price")
        update_price(sym, px)
        await _redis_set(f"price:{sym}", px, ex=30)
        return PriceResponse(ok=True, symbol=sym, price=float(px), source="binance", ts=time.time())
    except Exception as e:
        logger.error(f"[PRICE] exception for {sym}: {e}", exc_info=True)
        raise HTTPException(status_code=502, detail=str(e))





