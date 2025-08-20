# routes/price.py
from __future__ import annotations
from fastapi import APIRouter, Path
from pydantic import BaseModel
from typing import Optional, Any, Dict
import logging

# --- Utils ---
from utils.redis_client import redis_client
from utils.ws_fallback import get_price as get_cached_price, update_price
from utils.binance_client import futures_mark_price  # type: ignore

logger = logging.getLogger("algogpt.price")
router = APIRouter(tags=["Price"])  # ציבורי


class PriceResponse(BaseModel):
    ok: bool
    symbol: Optional[str] = None
    price: Optional[float] = None
    source: Optional[str] = None   # NEW: redis / cache / binance
    error: Optional[str] = None
    raw: Optional[Dict[str, Any]] = None


@router.get("/price", response_model=PriceResponse, operation_id="getPrice")
def get_price_hint() -> PriceResponse:
    return PriceResponse(ok=True, error="Use /price/{symbol} (e.g., /price/BTCUSDT)")


@router.get("/price/{symbol}", response_model=PriceResponse, operation_id="getPriceSymbol")
async def get_price_symbol(
    symbol: str = Path(..., min_length=3, example="BTCUSDT"),
) -> PriceResponse:
    symbol = symbol.upper()
    try:
        # --- שלב 1: Redis ---
        if redis_client:
            try:
                val = await redis_client.get(symbol)
                if val:
                    price = float(val)
                    return PriceResponse(ok=True, symbol=symbol, price=price, source="redis")
            except Exception as re:
                logger.warning(f"[PRICE] Redis unavailable: {re}")

        # --- שלב 2: cache מקומי (ws_fallback) ---
        local_price = get_cached_price(symbol)
        if local_price is not None:
            return PriceResponse(ok=True, symbol=symbol, price=float(local_price), source="cache")

        # --- שלב 3: Binance (fallback אחרון) ---
        data = futures_mark_price(symbol)
        if not data or not data.get("ok"):
            return PriceResponse(ok=False, symbol=symbol, error=str(data.get("error") if data else "unknown"))

        price = float(data.get("markPrice")) if data.get("markPrice") is not None else None

        # שמירה ב־cache המקומי + Redis
        if price is not None:
            update_price(symbol, price)
            if redis_client:
                try:
                    await redis_client.set(symbol, price, ex=30)  # Expire after 30s
                except Exception as se:
                    logger.warning(f"[PRICE] Failed storing {symbol} in Redis: {se}")

        return PriceResponse(
            ok=True,
            symbol=data.get("symbol"),
            price=price,
            source="binance",
            raw=data.get("raw"),
        )

    except Exception as e:
        logger.error(f"[PRICE] exception for {symbol}: {e}", exc_info=True)
        return PriceResponse(ok=False, symbol=symbol, error=str(e))




