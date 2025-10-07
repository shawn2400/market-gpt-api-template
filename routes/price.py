# routes/price.py
from __future__ import annotations
import asyncio, time, logging, os
from typing import Optional
from fastapi import APIRouter, Path, HTTPException
from pydantic import BaseModel
import httpx

# ws_fallback הוא רשותי: אם לא קיים – נשתמש בפונקציות no-op
try:
    from utils.ws_fallback import get_price as get_cached_price, update_price
except Exception:
    def get_cached_price(symbol: str) -> Optional[float]:  # type: ignore
        return None
    def update_price(symbol: str, price: float) -> None:  # type: ignore
        return None

# מחזיר float (סינכרוני)
from utils.binance_client import futures_mark_price  # type: ignore

# Redis רשותי
try:
    from utils.redis_client import redis_client  # type: ignore
except Exception:
    redis_client = None  # type: ignore

logger = logging.getLogger("algogpt.price")

router = APIRouter(prefix="/price", tags=["Price"])

BIN_FAPI = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com").rstrip("/")
BIN_SPOT = os.getenv("BINANCE_SPOT_HTTP_BASE", "https://api.binance.com").rstrip("/")

class PriceResponse(BaseModel):
    ok: bool
    symbol: Optional[str] = None
    price: Optional[float] = None
    source: Optional[str] = None   # redis/cache/binance_futures_client/binance_fapi/binance_fapi_ticker/binance_spot
    ts: Optional[float] = None
    error: Optional[str] = None

@router.get("/", response_model=PriceResponse, operation_id="getPriceHint", summary="Hint endpoint")
async def get_price_hint() -> PriceResponse:
    return PriceResponse(ok=True, error='Use /price/{symbol} (e.g., /price/BTCUSDT)')

async def _redis_get(key: str):
    if not redis_client:
        return None
    try:
        import inspect
        if inspect.iscoroutinefunction(getattr(redis_client, "get", None)):
            val = await redis_client.get(key)  # type: ignore
        else:
            val = redis_client.get(key)       # type: ignore
        return float(val) if val is not None else None
    except Exception as e:
        logger.warning(f"[PRICE] Redis get failed: {e}")
        return None

async def _redis_set(key: str, value: float, ex: int = 30):
    if not redis_client:
        return
    try:
        import inspect
        if inspect.iscoroutinefunction(getattr(redis_client, "set", None)):
            await redis_client.set(key, value, ex=ex)  # type: ignore
        else:
            redis_client.set(key, value, ex=ex)        # type: ignore
    except Exception as e:
        logger.warning(f"[PRICE] Redis set failed: {e}")

async def _binance_fapi_mark(symbol: str) -> Optional[float]:
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(f"{BIN_FAPI}/fapi/v1/premiumIndex", params={"symbol": symbol})
            if r.status_code != 200:
                return None
            data = r.json()
            if isinstance(data, list) and data:
                data = data[0]
            return float(data.get("markPrice", 0) or 0) or None
    except Exception as e:
        logger.warning(f"[PRICE] FAPI premiumIndex failed for {symbol}: {e}")
        return None

async def _binance_fapi_ticker(symbol: str) -> Optional[float]:
    """פולבאק נוסף: futures ticker/price (מחיר אחרון)"""
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(f"{BIN_FAPI}/fapi/v1/ticker/price", params={"symbol": symbol})
            if r.status_code != 200:
                return None
            data = r.json()
            return float(data.get("price", 0) or 0) or None
    except Exception as e:
        logger.warning(f"[PRICE] FAPI ticker/price failed for {symbol}: {e}")
        return None

async def _binance_spot_price(symbol: str) -> Optional[float]:
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(f"{BIN_SPOT}/api/v3/ticker/price", params={"symbol": symbol})
            if r.status_code != 200:
                return None
            data = r.json()
            return float(data.get("price", 0) or 0) or None
    except Exception as e:
        logger.warning(f"[PRICE] SPOT ticker failed for {symbol}: {e}")
        return None

@router.get("/{symbol}", response_model=PriceResponse, operation_id="getPriceSymbol", summary="Get latest price (multi-source fallback)")
async def get_price_symbol(symbol: str = Path(..., min_length=3, example="BTCUSDT")) -> PriceResponse:
    sym = symbol.upper().strip()

    # 1) Redis
    val = await _redis_get(f"price:{sym}")
    if val is not None:
        return PriceResponse(ok=True, symbol=sym, price=val, source="redis", ts=time.time())

    # 2) cache לוקלי
    local = get_cached_price(sym)
    if local is not None:
        return PriceResponse(ok=True, symbol=sym, price=float(local), source="cache", ts=time.time())

    # 3) utils.binance_client (סינכרוני – נריץ ב־thread)
    try:
        px = await asyncio.to_thread(futures_mark_price, sym)
        if px and px > 0:
            update_price(sym, px)
            await _redis_set(f"price:{sym}", px, ex=30)
            return PriceResponse(ok=True, symbol=sym, price=float(px), source="binance_futures_client", ts=time.time())
    except Exception as e:
        logger.warning(f"[PRICE] futures_mark_price failed for {sym}: {e}")

    # 4) FAPI premiumIndex (markPrice)
    mark = await _binance_fapi_mark(sym)
    if mark and mark > 0:
        update_price(sym, mark)
        await _redis_set(f"price:{sym}", mark, ex=30)
        return PriceResponse(ok=True, symbol=sym, price=float(mark), source="binance_fapi", ts=time.time())

    # 4b) FAPI ticker/price (last)
    last = await _binance_fapi_ticker(sym)
    if last and last > 0:
        update_price(sym, last)
        await _redis_set(f"price:{sym}", last, ex=30)
        return PriceResponse(ok=True, symbol=sym, price=float(last), source="binance_fapi_ticker", ts=time.time())

    # 5) Spot ticker
    spot = await _binance_spot_price(sym)
    if spot and spot > 0:
        update_price(sym, spot)
        await _redis_set(f"price:{sym}", spot, ex=30)
        return PriceResponse(ok=True, symbol=sym, price=float(spot), source="binance_spot", ts=time.time())

    raise HTTPException(status_code=502, detail="Unable to fetch price for symbol")








