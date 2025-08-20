# routes/price.py
from __future__ import annotations
from fastapi import APIRouter, Path
from pydantic import BaseModel, Field
from typing import Optional, Any, Dict

router = APIRouter(tags=["Price"])  # ציבורי

class PriceResponse(BaseModel):
    ok: bool
    symbol: Optional[str] = None
    price: Optional[float] = None
    endpoint: Optional[str] = None
    error: Optional[str] = None
    raw: Optional[Dict[str, Any]] = None

@router.get("/price", response_model=PriceResponse, operation_id="getPrice")
def get_price_hint() -> PriceResponse:
    return PriceResponse(ok=True, error="Use /price/{symbol} (e.g., /price/BTCUSDT)")

@router.get("/price/{symbol}", response_model=PriceResponse, operation_id="getPriceSymbol")
def get_price_symbol(
    symbol: str = Path(..., min_length=3, example="BTCUSDT"),
) -> PriceResponse:
    try:
        from utils.binance_client import futures_mark_price  # type: ignore
        data = futures_mark_price(symbol)
        if not data or not data.get("ok"):
            return PriceResponse(ok=False, symbol=symbol.upper(), error=str(data.get("error") if data else "unknown"))
        return PriceResponse(
            ok=True,
            symbol=data.get("symbol"),
            price=float(data.get("markPrice")) if data.get("markPrice") is not None else None,
            endpoint=data.get("endpoint"),
            raw=data.get("raw"),
        )
    except Exception as e:
        return PriceResponse(ok=False, symbol=symbol.upper(), error=str(e))



