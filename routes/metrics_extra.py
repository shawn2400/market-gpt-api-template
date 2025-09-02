# routes/metrics_extra.py
from __future__ import annotations
from typing import List, Dict, Any
from fastapi import APIRouter, Depends, Path, Query, Request, HTTPException
from utils.auth import require_api_key
from utils.derivatives_metrics import long_short_ratio, taker_delta_volume, funding_heatmap

router = APIRouter(prefix="/metrics", tags=["Metrics"], dependencies=[Depends(require_api_key)])

# rate limiter פשוט
_rl: Dict[str, list] = {}
def _allow(ip: str, limit=20, window=60.0) -> bool:
    import time
    now = time.time()
    arr = [t for t in _rl.get(ip, []) if now - t < window]
    if len(arr) >= limit:
        return False
    arr.append(now); _rl[ip] = arr; return True

@router.get("/longshort/{symbol}")
def api_longshort(
    symbol: str = Path(..., description="e.g. BTCUSDT"),
    period: str = Query("5m"),
    limit: int = Query(30, ge=1, le=500),
    source: str = Query("global", description="global | topAccounts | topPositions"),
    request: Request = None
) -> Dict[str, Any]:
    if not _allow(request.client.host): raise HTTPException(429, "Rate limit exceeded")
    return long_short_ratio(symbol, period=period, limit=limit, source=source)

@router.get("/delta_volume/{symbol}")
def api_delta_volume(
    symbol: str = Path(..., description="e.g. BTCUSDT"),
    period: str = Query("5m"),
    limit: int = Query(30, ge=1, le=500),
    request: Request = None
) -> Dict[str, Any]:
    if not _allow(request.client.host): raise HTTPException(429, "Rate limit exceeded")
    return taker_delta_volume(symbol, period=period, limit=limit)

@router.get("/funding/heatmap")
def api_funding_heatmap(
    symbols: str = Query(..., description="CSV e.g. BTCUSDT,ETHUSDT,SOLUSDT"),
    limit: int = Query(24, ge=1, le=1000),
    request: Request = None
) -> Dict[str, Any]:
    if not _allow(request.client.host): raise HTTPException(429, "Rate limit exceeded")
    syms = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    return funding_heatmap(syms, limit=limit)
