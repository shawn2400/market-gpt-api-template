# routes/orderflow.py
from __future__ import annotations
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel

from utils.auth import require_api_key

logger = logging.getLogger("algogpt.routes.orderflow")
router = APIRouter(tags=["orderflow"])

try:
    from utils.orderflow import get_orderflow_snapshot as _calc_orderflow
    _CALC_ERR = None
except Exception as e:
    _calc_orderflow = None
    _CALC_ERR = str(e)
    logger.warning("orderflow calc not available: %s", e)

# ---- מודלים ל-OpenAPI ----
class CVD(BaseModel):
    cvd: float
    buy_vol: float
    sell_vol: float
    buy_share: float
    sell_share: float

class DepthImbalance(BaseModel):
    bid_vol: float
    ask_vol: float
    imbalance: float

class Depth(BaseModel):
    best_bid: float
    best_ask: float
    mid: float
    imbalance: DepthImbalance

class Limits(BaseModel):
    trades: int
    depth: int
    cvd_window: int

class OrderflowOut(BaseModel):
    ok: bool = True
    symbol: str
    limits: Limits
    cvd: CVD
    depth: Depth

@router.get("/__of_ping", summary="Orderflow router ping", include_in_schema=True, response_model=dict)
def __of_ping() -> dict[str, Any]:
    return {
        "ok": True,
        "route": "/__of_ping",
        "calc_loaded": bool(_calc_orderflow),
        "version": "1.0",
    }

@router.get(
    "/orderflow/{symbol}",
    response_model=OrderflowOut,
    response_model_exclude_none=True,
    summary="Orderflow snapshot (protected)",
    dependencies=[Depends(require_api_key)],   # המידלוור הכללי גם מגן, זה חיזוק
)
def orderflow(
    symbol: str = Path(..., min_length=1),
    trades_limit: int = Query(200, ge=1, le=2000),
    depth_limit: int = Query(50, ge=1, le=5000),
    cvd_window: int = Query(60, ge=1, le=100000),
) -> OrderflowOut:
    if _calc_orderflow is None:
        raise HTTPException(status_code=503, detail=f"orderflow_calc_unavailable: {_CALC_ERR or 'unknown'}")
    data = _calc_orderflow(
        symbol,
        trades_limit=trades_limit,
        depth_limit=depth_limit,
        cvd_window=cvd_window,
    )
    data.setdefault("ok", True)
    return OrderflowOut(**data)













  

