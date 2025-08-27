# routes/executor.py
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from typing import List, Dict, Any

from utils.auth import require_api_key
from utils.binance_client import futures_open_positions, futures_exchange_info_safe
from utils.trade_manager import get_open_trades, get_trade_history

router = APIRouter(prefix="/executor", tags=["Executor"], dependencies=[Depends(require_api_key)])


@router.get("/positions", response_model=List[Dict[str, Any]])
def list_open_positions() -> List[Dict[str, Any]]:
    """מחזיר רשימת פוזיציות פתוחות ב-Binance Futures"""
    try:
        return futures_open_positions() or []
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch positions: {e}")


@router.get("/open_positions", response_model=List[Dict[str, Any]])
def alias_open_positions():
    """Alias ל־/positions"""
    return list_open_positions()


@router.get("/symbols", response_model=List[str])
def list_symbols() -> List[str]:
    """רשימת כל הסימבולים ב־Binance Futures"""
    try:
        info = futures_exchange_info_safe(force_refresh=False)
        return [s["symbol"] for s in info.get("symbols", [])]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch symbols: {e}")


@router.get("/trades", response_model=List[Dict[str, Any]])
def list_trades(limit: int = 50):
    """מחזיר היסטוריית טריידים"""
    try:
        return get_trade_history(limit=limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch trades: {e}")


@router.get("/status")
def executor_status() -> Dict[str, Any]:
    """סטטוס Executor"""
    return {"ok": True, "executor": "running", "positions_endpoint": "/executor/positions"}


















