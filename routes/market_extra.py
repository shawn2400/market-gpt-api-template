# routes/market_extra.py
# ======================
from __future__ import annotations
from fastapi import APIRouter, Query, Depends, HTTPException
from typing import List, Dict, Any
from utils.auth import require_api_key
from utils.binance_client import futures_mark_price
from utils.derivatives_metrics import funding_heatmap

router = APIRouter(
    prefix="/market",
    tags=["MarketExtra"],
    dependencies=[Depends(require_api_key)]
)

@router.get("/tickers")
def tickers(symbols: str = Query(..., description="Comma separated list, e.g. BTCUSDT,ETHUSDT")) -> List[Dict[str, Any]]:
    """החזרת MarkPrice לכמה סימבולים במכה אחת (Futures)."""
    out: List[Dict[str, Any]] = []
    for sym in [s.strip().upper() for s in symbols.split(",") if s.strip()]:
        price = futures_mark_price(sym)
        out.append({"symbol": sym, "markPrice": price})
    return out

@router.get("/funding", summary="Funding rates (alias)", description="אליאס נוח ל-/metrics/funding/heatmap עבור סימבול/ים.")
def funding(
    symbol: str | None = Query(None, description="סימבול יחיד, למשל BTCUSDT"),
    symbols: str | None = Query(None, description="רשימה מופרדת בפסיקים, למשל BTCUSDT,ETHUSDT"),
    limit: int = Query(24, ge=1, le=1000)
) -> Dict[str, Any]:
    syms: List[str] = []
    if symbols:
        syms.extend([s.strip().upper() for s in symbols.split(",") if s.strip()])
    if symbol:
        syms.append(symbol.strip().upper())
    syms = [s for s in syms if s]
    if not syms:
        raise HTTPException(status_code=400, detail="symbol or symbols required")
    return funding_heatmap(syms, limit=limit)




