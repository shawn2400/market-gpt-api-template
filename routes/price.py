# routes/price.py
from __future__ import annotations
from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel, Field
from typing import Optional

router = APIRouter(prefix="", tags=["Price"])

# Auth
try:
    from utils.auth import require_bearer_token
except Exception:
    def require_bearer_token():
        raise HTTPException(status_code=401, detail="Not authenticated")

# Binance client (פונקציה כללית לקבל מחיר)
try:
    from utils.binance_client import get_price  # אתה כבר משתמש בלקוח הזה בעצמך
except Exception as e:
    get_price = None  # type: ignore

class PriceResponse(BaseModel):
    symbol: str = Field(..., example="BTCUSDT")
    price: float = Field(..., example=117582.4)
    market: str = Field(..., example="futures")  # or "spot"
    ts: Optional[int] = Field(None, description="server timestamp if available")

def _normalize_symbol(s: str) -> str:
    return (s or "").upper().replace("-", "").replace(" ", "")

async def _fetch_price(symbol: str, market: str) -> PriceResponse:
    if get_price is None:
        raise HTTPException(status_code=500, detail="binance client not available")
    try:
        px, ts = await get_price(symbol=symbol, market=market)  # הקפד ש-signature מתיישר עם שלך
        return PriceResponse(symbol=symbol, price=float(px), market=market, ts=int(ts) if ts else None)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"price fetch failed: {e}")

@router.get("/price", response_model=PriceResponse, summary="Get last price by query param")
async def price_query(
    symbol: str = Query(..., description="e.g., BTCUSDT"),
    market: str = Query("futures", regex="^(spot|futures)$"),
    _: None = Depends(require_bearer_token),
):
    return await _fetch_price(_normalize_symbol(symbol), market)

@router.get("/price/{symbol}", response_model=PriceResponse, summary="Get last price by path param")
async def price_path(
    symbol: str,
    market: str = Query("futures", regex="^(spot|futures)$"),
    _: None = Depends(require_bearer_token),
):
    return await _fetch_price(_normalize_symbol(symbol), market)
