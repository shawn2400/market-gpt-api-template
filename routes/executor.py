# routes/executor.py
from __future__ import annotations
import logging
from typing import Dict, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from utils.auth import require_api_key
from utils.binance_client import (
    fapi_ping,
    futures_open_positions_safe,
    futures_balance,
    futures_mark_price,
    futures_exchange_info_safe,
)
from utils.trade_executor import execute_trade_live

logger = logging.getLogger("algogpt.routes.executor")

router = APIRouter(
    prefix="/executor",
    tags=["Executor"],
    dependencies=[Depends(require_api_key)],
)

# ─────────────────────────────
# Models
# ─────────────────────────────
class TradeRequest(BaseModel):
    symbol: str
    side: str
    budget: float
    leverage: int = 10
    reduce_only: bool = False

# ─────────────────────────────
# Endpoints
# ─────────────────────────────
@router.get("/ping")
async def ping() -> Dict[str, Any]:
    return {"ok": fapi_ping()}

@router.get("/status")
async def status() -> Dict[str, Any]:
    return {"ok": True, "status": "running"}

@router.get("/positions")
async def open_positions(symbol: Optional[str] = Query(None)) -> Dict[str, Any]:
    try:
        pos = futures_open_positions_safe(symbol)
        return {"ok": True, "positions": pos}
    except Exception as e:
        logger.error("positions failed: %s", e)
        raise HTTPException(500, str(e))

@router.get("/balance")
async def balance() -> Dict[str, Any]:
    try:
        return {"ok": True, "balances": futures_balance()}
    except Exception as e:
        logger.error("balance failed: %s", e)
        raise HTTPException(500, str(e))

@router.get("/mark-price")
async def mark_price(symbol: str = Query(...)) -> Dict[str, Any]:
    try:
        px = futures_mark_price(symbol)
        if px is None:
            raise RuntimeError("mark price unavailable")
        return {"ok": True, "symbol": symbol.upper(), "markPrice": px}
    except Exception as e:
        logger.error("mark-price failed: %s", e)
        raise HTTPException(500, str(e))

@router.get("/exchange-info")
async def exchange_info() -> Dict[str, Any]:
    try:
        return {"ok": True, "info": futures_exchange_info_safe()}
    except Exception as e:
        logger.error("exchange-info failed: %s", e)
        raise HTTPException(500, str(e))

@router.post("/trade")
async def trade(req: TradeRequest) -> Dict[str, Any]:
    try:
        res = await execute_trade_live(
            symbol=req.symbol,
            side=req.side,
            budget=req.budget,
            leverage=req.leverage,
            reduce_only=req.reduce_only,
        )
        return {"ok": True, "result": res}
    except Exception as e:
        logger.error("trade failed: %s", e)
        raise HTTPException(500, str(e))


































