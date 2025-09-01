# routes/market_extra.py
from __future__ import annotations
from fastapi import APIRouter, Query, Depends
from typing import List, Dict, Any
from utils.auth import require_api_key
from utils.binance_client import futures_mark_price

router = APIRouter(
    prefix="/market",
    tags=["MarketExtra"],
    dependencies=[Depends(require_api_key)]
)

@router.get("/tickers")
def tickers(symbols: str = Query(..., description="Comma separated list, e.g. BTCUSDT,ETHUSDT")) -> List[Dict[str, Any]]:
    """החזרת MarkPrice לכמה סימבולים במכה אחת"""
    out: List[Dict[str, Any]] = []
    for sym in [s.strip().upper() for s in symbols.split(",") if s.strip()]:
        price = futures_mark_price(sym)
        out.append({"symbol": sym, "markPrice": price})
    return out


