# routes/orderflow.py
# =========================
# REST API לניתוח Orderflow (CVD, Depth)
# =========================
from __future__ import annotations
import asyncio, time
from typing import Dict, Any, Optional
from fastapi import APIRouter, Depends, Path, Query, Request, HTTPException
from utils.auth import require_api_key
from utils.orderflow import get_orderflow_snapshot

router = APIRouter(tags=["Analytics"], dependencies=[Depends(require_api_key)])

# --- Rate limit פנימי
_rl_state: dict[str, list[float]] = {}
def _rl(ip: str, limit=15, window=60):
    now = time.time()
    calls = [c for c in _rl_state.get(ip, []) if now - c < window]
    if len(calls) >= limit:
        return False
    calls.append(now)
    _rl_state[ip] = calls
    return True

@router.get("/orderflow/{symbol}", summary="Orderflow snapshot", response_model=None)
async def get_orderflow(
    symbol: str = Path(..., description="e.g. BTCUSDT"),
    trades_limit: int = Query(800, ge=1, le=1000),
    depth_limit: int = Query(500, ge=5, le=1000),
    cvd_window: int = Query(300, ge=1, le=1000),
    request: Request | None = None,
) -> Dict[str, Any]:
    ip = None
    try:
        ip = request.client.host if request and request.client else None
    except Exception:
        ip = None
    if ip and not _rl(ip):
        raise HTTPException(429, "Rate limit exceeded")
    return await asyncio.to_thread(
        get_orderflow_snapshot,
        symbol,
        trades_limit=trades_limit,
        depth_limit=depth_limit,
        cvd_window=cvd_window
    )








  

