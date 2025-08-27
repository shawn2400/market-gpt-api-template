# routes/executor_extra.py
from __future__ import annotations
from fastapi import APIRouter, Depends
from typing import List, Dict, Any

from utils.auth import require_api_key
from utils.binance_client import futures_exchange_info_safe, futures_open_positions
from utils.trade_manager import get_trade_history

router = APIRouter(
    prefix="/executor",
    tags=["ExecutorExtra"],
    dependencies=[Depends(require_api_key)]
)

@router.get("/symbols")
def executor_symbols() -> List[str]:
    """רשימת כל הסימבולים הזמינים ב-Binance Futures"""
    info = futures_exchange_info_safe()
    return [s["symbol"] for s in info.get("symbols", [])]

@router.get("/open_positions")
def open_positions() -> List[Dict[str, Any]]:
    """פוזיציות פתוחות (כמו /positions)"""
    return futures_open_positions() or []

@router.get("/trades")
def executor_trades(limit: int = 50) -> List[Dict[str, Any]]:
    """היסטוריית טריידים מה־trade_manager"""
    return get_trade_history(limit=limit)

