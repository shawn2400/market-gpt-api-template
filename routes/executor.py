# routes/executor.py
from __future__ import annotations
import logging
from typing import Dict, Any, Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ConfigDict

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

class ExecTradeRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    symbol: str = Field(..., examples=["BTCUSDT"], min_length=3)
    side: str = Field(..., examples=["BUY", "SELL"])
    leverage: int = Field(10, ge=1, le=125)
    budget_usd: Optional[float] = Field(None, ge=0, description="תקציב ב-USD (מועדף)")
    budget: Optional[float] = Field(None, ge=0, description="שם ישן — שקול ל-budget_usd")
    quantity: Optional[float] = Field(None, ge=0)
    entry: Optional[float] = Field(None)
    sl: Optional[float] = Field(None)
    tp: Optional[float] = Field(None)
    tp_targets: Optional[List[float]] = None
    tp_splits: Optional[List[float]] = None
    sl_targets: Optional[List[float]] = None
    sl_splits: Optional[List[float]] = None
    dry_run: bool = Field(True, description="True = סימולציה בלבד")
    confirm_first: bool = Field(True, description="אישור בטלגרם לפני ביצוע")
    telegram_chat_id: Optional[int] = Field(None)

@router.get("/ping")
async def ping() -> Dict[str, Any]:
    try:
        return {"ok": bool(fapi_ping())}
    except Exception as e:
        logger.warning("executor/ping failed: %s", e)
        return {"ok": False}

@router.get("/status")
async def status() -> Dict[str, Any]:
    return {"ok": True, "status": "running"}

@router.get("/positions")
async def open_positions(symbol: Optional[str] = Query(None, min_length=3)) -> Dict[str, Any]:
    try:
        return {"ok": True, "positions": futures_open_positions_safe(symbol)}
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

@






























