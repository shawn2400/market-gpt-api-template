# routes/executor_extra.py
from __future__ import annotations
import logging
from typing import Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query

from utils.auth import require_api_key
from utils.binance_client import (
    futures_open_positions_safe,
    futures_balance_safe,
    futures_exchange_info_safe,
    futures_mark_price_safe,
)

logger = logging.getLogger("algogpt.executor_extra")

router = APIRouter(
    prefix="/executor-extra",
    tags=["Executor Extra"],
    dependencies=[Depends(require_api_key)],
)


@router.get("/positions", summary="List open futures positions")
async def list_positions(_: Any = Depends(require_api_key)) -> Dict[str, Any]:
    """
    מחזיר את כל הפוזיציות הפתוחות בחשבון Futures.
    """
    try:
        positions = futures_open_positions_safe()
        return {"ok": True, "positions": positions}
    except Exception as e:
        logger.exception("[executor_extra] positions error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/balance", summary="Get futures account balance")
async def get_balance(_: Any = Depends(require_api_key)) -> Dict[str, Any]:
    """
    מחזיר יתרות Futures בחשבון.
    """
    try:
        bal = futures_balance_safe()
        return {"ok": True, "balance": bal}
    except Exception as e:
        logger.exception("[executor_extra] balance error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/exchange-info", summary="Get futures exchange info")
async def get_exchange_info(_: Any = Depends(require_api_key)) -> Dict[str, Any]:
    """
    מחזיר את ה־exchangeInfo של Binance Futures.
    """
    try:
        info = futures_exchange_info_safe()
        return {"ok": True, "exchangeInfo": info}
    except Exception as e:
        logger.exception("[executor_extra] exchangeInfo error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/mark-price", summary="Get futures mark price")
async def get_mark_price(
    symbol: str = Query(..., description="Symbol לדוגמה: BTCUSDT"),
    _: Any = Depends(require_api_key),
) -> Dict[str, Any]:
    """
    מחזיר Mark Price של סימבול ב־Futures.
    """
    try:
        mp = futures_mark_price_safe(symbol)
        return {"ok": True, "symbol": symbol, "markPrice": mp}
    except Exception as e:
        logger.exception("[executor_extra] markPrice error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))







