# routes/indicators_extra.py
from __future__ import annotations
from typing import Dict, Any
from fastapi import APIRouter, Depends, Path, Query, Request, HTTPException
from utils.auth import require_api_key
from utils.indicators_extra import advanced_indicators

router = APIRouter(prefix="/indicators", tags=["IndicatorsExtra"], dependencies=[Depends(require_api_key)])

_rl = {}
def _allow(ip: str, limit=20, window=60):
    import time
    now = time.time()
    arr = [t for t in _rl.get(ip, []) if now - t < window]
    if len(arr) >= limit: return False
    arr.append(now); _rl[ip] = arr; return True

@router.get("/advanced/{symbol}")
def api_adv(
    symbol: str = Path(..., description="e.g. BTCUSDT"),
    interval: str = Query("15m"),
    limit: int = Query(200, ge=50, le=1500),
    market: str = Query("futures"),
    with_cvd: bool = Query(False),
    request: Request = None
) -> Dict[str, Any]:
    if not _allow(request.client.host): raise HTTPException(429, "Rate limit exceeded")
    return advanced_indicators(symbol, interval=interval, limit=limit, market=market, with_cvd=with_cvd)
