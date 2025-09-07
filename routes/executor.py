# routes/export.py
from __future__ import annotations
import logging
from typing import Dict, Any, List
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from utils.auth import require_api_key

# ניהול טריידים
try:
    from utils.open_trade_manager import manage_open_trades, bulk_manage_trades  # type: ignore
except Exception:
    manage_open_trades = None  # type: ignore
    bulk_manage_trades = None  # type: ignore

# נתוני Binance
try:
    from utils.binance_client import (  # type: ignore
        futures_balance,
        get_open_positions,
        futures_mark_price,
        futures_exchange_info_safe as _exchange_info_primary,
    )
except Exception:
    futures_balance = None
    get_open_positions = None
    futures_mark_price = None
    _exchange_info_primary = None

logger = logging.getLogger("algogpt.export")

router = APIRouter(
    prefix="/export",
    tags=["Export"],
    dependencies=[Depends(require_api_key)],
)

class TradeRequest(BaseModel):
    symbol: str
    side: str
    qty: float
    entry_price: float
    sl_price: float
    tp_price: float
    leverage: int = 10
    position_side: str = "BOTH"

class BulkTradeRequest(BaseModel):
    trades: List[TradeRequest]

def _safe_exchange_info() -> Dict[str, Any]:
    if callable(_exchange_info_primary):
        try:
            info = _exchange_info_primary()
            if isinstance(info, dict) and info:
                return info
        except Exception as e:
            logger.warning("[export] exchange_info primary failed: %s", e)
    return {"symbols": []}

@router.get("/status")
async def export_status() -> Dict[str, Any]:
    return {"ok": True, "status": "export-ready"}

































