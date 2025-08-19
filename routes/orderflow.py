# routes/orderflow.py
from __future__ import annotations
from typing import Dict, Any
from fastapi import APIRouter, Depends, Path, Query
from utils.auth import require_bearer_token
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
    return await get_orderflow_snapshot(symbol, trades_limit=trades_limit, depth_limit=depth_limit, cvd_window=cvd_window)


  

