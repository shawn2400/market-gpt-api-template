# routes/orderflow.py
from __future__ import annotations
import asyncio
from typing import Dict, Any

from fastapi import APIRouter, Depends, Path, Query, HTTPException

try:
    from utils.auth import require_bearer_token
except Exception:
    def require_bearer_token():
        raise HTTPException(status_code=401, detail="Unauthorized")

from utils.orderflow import get_orderflow_snapshot

router = APIRouter(tags=["Analytics"], dependencies=[Depends(require_bearer_token)])

@router.get(
    "/orderflow/{symbol}",
    summary="Orderflow snapshot (CVD / Depth / Icebergs)",
    operation_id="getOrderflowSnapshot",
)
async def get_orderflow(
    symbol: str = Path(..., description="e.g. BTCUSDT"),
    trades_limit: int = Query(800, ge=1, le=1000, description="aggTrades to pull (<=1000)"),
    depth_limit: int = Query(500, ge=5, le=1000, description="order book levels (5..1000)"),
    cvd_window: int = Query(300, ge=1, le=1000, description="trades window for CVD"),
) -> Dict[str, Any]:
    """
    מחזיר תצלום Order Flow מיידי:
    - CVD + יחסי קניה/מכירה
    - דאפית׳: אימבלאנס, bid/ask volumes, best bid/ask
    - אזכור Icebergs (היוריסטי)
    """
    result = await asyncio.to_thread(
        get_orderflow_snapshot,
        symbol,
        trades_limit=trades_limit,
        depth_limit=depth_limit,
        cvd_window=cvd_window,
    )
    return result


