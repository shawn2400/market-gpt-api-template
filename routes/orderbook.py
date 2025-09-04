# routes/orderbook.py
# ===================
from __future__ import annotations
from typing import Dict, Any
from fastapi import APIRouter, Depends, Path, Query
from utils.auth import require_api_key
from utils.orderbook import fetch_depth, get_orderbook_pressure

router = APIRouter(prefix="/orderbook", tags=["Orderbook"], dependencies=[Depends(require_api_key)])

@router.get("/depth/{symbol}")
def api_depth(
    symbol: str = Path(..., description="e.g. BTCUSDT"),
    limit: int = Query(100, ge=5, le=1000),
    market: str = Query("futures", description="futures|spot"),
) -> Dict[str, Any]:
    return fetch_depth(symbol, limit=limit, market=market)

@router.get("/pressure/{symbol}")
def api_pressure(
    symbol: str = Path(..., description="e.g. BTCUSDT"),
    limit: int = Query(100, ge=5, le=1000),
    top_levels: int = Query(20, ge=1, le=1000),
    market: str = Query("futures", description="futures|spot"),
) -> Dict[str, Any]:
    return get_orderbook_pressure(symbol, market=market, limit=limit, top_levels=top_levels)


