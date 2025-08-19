# routes/orderflow.py
from __future__ import annotations
from typing import Dict, Any
import asyncio
from fastapi import APIRouter, Depends, Path, Query, HTTPException

try:
    from utils.auth import require_bearer_token
except Exception:
    def require_bearer_token(*_, **__):
        raise HTTPException(status_code=401, detail="Unauthorized")

from utils.orderflow import get_orderflow_snapshot

router = APIRouter(tags=["Analytics"], dependencies=[Depends(require_bearer_token)])

@router.get(
    "/orderflow/{symbol}",
    summary="Orderflow snapshot (CVD / Depth / Taker stats)",
    operation_id="getOrderflowSnapshot",
)
async def orderflow(
    symbol: str = Path(..., description="e.g. BTCUSDT"),
    trades_limit: int = Query(800, ge=1, le=1000),
    depth_limit: int = Query(500, ge=5, le=1000),
    cvd_window: int = Query(300, ge=1, le=1000),
) -> Dict[str, Any]:
    return await asyncio.to_thread(
        asyncio.run,  # הרצת קורוטינה בסינכרוני
        get_orderflow_snapshot(symbol, trades_limit=trades_limit, depth_limit=depth_limit, cvd_window=cvd_window)
    )

