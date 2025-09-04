# routes/executor.py
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Dict, Any

from utils.auth import require_api_key
from utils.binance_client import futures_mark_price, futures_balance, futures_open_positions

router = APIRouter(
    prefix="/executor",
    tags=["Executor"],
    dependencies=[Depends(require_api_key)],
)

@router.get("/status")
def executor_status() -> Dict[str, Any]:
    """סטטוס כללי של ה-Executor כולל פוזיציות פתוחות ויתרה."""
    try:
        balance = futures_balance()
        positions = futures_open_positions()
        return {"ok": True, "executor": "running", "balance": balance, "positions": positions}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"executor_status failed: {e}")

@router.get("/mark_price")
def get_mark_price(symbol: str = Query(..., description="e.g. BTCUSDT")) -> Dict[str, Any]:
    """מחזיר Mark Price חי מסימבול מסוים."""
    try:
        price = futures_mark_price(symbol)
        if not price:
            raise ValueError("No mark price available")
        return {"ok": True, "symbol": symbol.upper(), "mark_price": float(price)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"get_mark_price failed: {e}")



























