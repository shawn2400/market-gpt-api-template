# routes/orderflow.py
# =========================
# Orderflow API Route – מחזיר snapshot של Orderflow
# =========================

from __future__ import annotations
import asyncio
from typing import Dict, Any
from fastapi import APIRouter, Depends, Path, Query

from utils.auth import require_api_key
from utils.orderflow import get_orderflow_snapshot

# ✅ משתמשים ב־require_api_key במקום require_bearer_token
router = APIRouter(tags=["Analytics"], dependencies=[Depends(require_api_key)])

@router.get(
    "/orderflow/{symbol}",
    summary="Orderflow snapshot (CVD / Depth / Imbalance / Icebergs heuristic)",
    operation_id="getOrderflowSnapshot",
)
async def get_orderflow(
    symbol: str = Path(..., description="e.g. BTCUSDT"),
    trades_limit: int = Query(800, ge=1, le=1000, description="aggTrades to pull (<=1000)"),
    depth_limit: int = Query(500, ge=5, le=1000, description="order book levels (5..1000)"),
    cvd_window: int = Query(300, ge=1, le=1000, description="trades window for CVD"),
) -> Dict[str, Any]:
    """
    Endpoint שמחזיר תמונת מצב של Orderflow:
    - CVD (Cumulative Volume Delta)
    - עומק ספר פקודות
    - Imbalance
    - Heuristic לאיתור Icebergs
    """
    result = await asyncio.to_thread(
        get_orderflow_snapshot,
        symbol,
        trades_limit=trades_limit,
        depth_limit=depth_limit,
        cvd_window=cvd_window,
    )
    return result






  

