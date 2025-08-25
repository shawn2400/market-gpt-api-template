# routes/price.py
from __future__ import annotations
import asyncio, time, logging, os
from typing import Optional
from fastapi import APIRouter, Path, HTTPException
from pydantic import BaseModel
import httpx

# קאש מקומי בתוך התהליך (ws_fallback)
from utils.ws_fallback import get_price as get_cached_price, update_price
# לקוח פנימי שמחזיר float למחיר מרקט (מועדף)
from utils.binance_client import futures_mark_price  # must return float

# Redis יכול להיות sync או async – נטפל בשניהם
try:
    from utils.redis_client import redis_client  # יכול להיות None או אובייקט sync/async
except Exception:
    redis_client = None  # type: ignore

logger = logging.getLogger("algogpt.price")

# ⚠️ חשוב: prefix=/price כדי שתקבל /price ו-/price/{symbol}
router = APIRouter(prefix="/price", tags=["Price"])

BIN_FAPI = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com").rstrip("/")
BIN_SPOT = os.getenv("BINANCE_SPOT_HTTP_BASE", "https://api.binance.com").rstrip("/")
TTL = int(os.getenv("PRICE_WS_FRESH_TTL", "20"))

class PriceResponse(BaseModel):
    ok: bool
    symbol: Optional[str] = None
    price: Optional[float] = None
    source: Optional[str] = None   # redis/cache/binance_futures_client/binance_fapi/binance_spot
    ts: Optional[float] = None
    error: Optional[str] = None

@router.get("/", response_model=PriceResponse, operation_id="getPriceHint")
async def get_price_hint() -> PriceResponse:
    return PriceResponse(ok=True, error='Use /price/{symbol} (e.g., /price/BTCUSDT)')

async def _redis_get(key: str) -> Optional[float]:
    if not redis_client:
        return None
    try:
        import inspect
        if inspect.iscoroutinefunction(getattr(redis_client, "get", None)):
            val = await redis_client.get(key)  # type: ignore
        else:
            val = redis_client.get(key)        # type: ignore
        if val is None:
            return None
        if isinstance(val, (bytes, bytearray)):
            val = val.decode()
        return float(val)
    except Exception as e:
        logger.warning(f"[PRICE] Redis get failed: {e}")
        return None

async def _redis_set(key: str, value: float, ex: int = 30) -> None:
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
    # GET /fapi/v1/premiumIndex?symbol=SYMBOL -> { markPrice }
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(f"{BIN_FAPI}/fapi/v1/premiumIndex", params={"symbol": symbol})
            if r.status_code != 200:
                return None
            data = r.json()
            return float(data.get("markPrice", 0) or 0)
    except Exception:
        return None

async def _binance_spot_price(symbol: str) -> Optional[float]:
    # GET /api/v3/ticker/price?symbol=SYMBOL -> { price }
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(f"{BIN_SPOT}/api/v3/ticker/price", params={"symbol": symbol})
            if r.status_code != 200:
                return None
            data = r.json()
            return float(data.get("price", 0) or 0)
    except Exception:
        return None

@router.get("/{symbol}", response_model=PriceResponse, operation_id="getPriceSymbol")
async def get_price_symbol(symbol: str = Path(..., min_length=3, example="BTCUSDT")) -> PriceResponse:
    sym = symbol.upper().strip()

    # 1) Redis קודם
    val = await _redis_get(f"price:{sym}")
    if val is not None and val > 0:
        return PriceResponse(ok=True, symbol=sym, price=val, source="redis", ts=time.time())

    # 2) קאש מקומי בתהליך
    local = get_cached_price(sym)
    if local is not None and float(local) > 0:
        return PriceResponse(ok=True, symbol=sym, price=float(local), source="cache", ts=time.time())

    # 3) לקוח פנימי (מעדיף Futures Mark Price דרך utils.binance_client)
    try:
        px = await asyncio.to_thread(futures_mark_price, sym)  # שמירה על תאימות
        if px and float(px) > 0:
            update_price(sym, float(px))
            await _redis_set(f"price:{sym}", float(px), ex=30)
            return PriceResponse(ok=True, symbol=sym, price=float(px), source="binance_futures_client", ts=time.time())
    except Exception as e:
        logger.warning(f"[PRICE] futures_mark_price failed for {sym}: {e}")

    # 4) FAPI premiumIndex (markPrice) — פאולבק קשיח
    mark = await _binance_fapi_mark(sym)
    if mark and mark > 0:
        update_price(sym, mark)
        await _redis_set(f"price:{sym}", mark, ex=30)
        return PriceResponse(ok=True, symbol=sym, price=float(mark), source="binance_fapi", ts=time.time())

    # 5) Spot ticker — פאולבק אחרון
    spot = await _binance_spot_price(sym)
    if spot and spot > 0:
        update_price(sym, spot)
        await _redis_set(f"price:{sym}", spot, ex=30)
        return PriceResponse(ok=True, symbol=sym, price=float(spot), source="binance_spot", ts=time.time())

    raise HTTPException(status_code=502, detail="Unable to fetch price for symbol")







