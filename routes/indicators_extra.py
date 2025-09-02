# routes/indicators_extra.py
from __future__ import annotations
from fastapi import APIRouter, Depends, Path, Query
from typing import Dict, Any

from utils.auth import require_api_key
from utils.indicators_ext import advanced_indicators

router = APIRouter(prefix="/indicators", tags=["IndicatorsExtra"], dependencies=[Depends(require_api_key)])

@router.get("/advanced/{symbol}")
def api_advanced_indicators(
    symbol: str = Path(..., description="e.g. BTCUSDT"),
    interval: str = Query("15m"),
    limit: int = Query(200, ge=50, le=1500),
    market: str = Query("futures"),
    with_cvd: bool = Query(False),
) -> Dict[str, Any]:
    return advanced_indicators(symbol, interval=interval, limit=limit, market=market, with_cvd=with_cvd)


