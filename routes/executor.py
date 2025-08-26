# routes/executor.py
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from typing import List, Dict, Any

from utils.auth import require_api_key
from utils.binance_client import futures_open_positions

router = APIRouter(
    prefix="/executor",
    dependencies=[Depends(require_api_key)],
)

@router.get("/positions", response_model=List[Dict[str, Any]])
def list_open_positions() -> List[Dict[str, Any]]:
    """
    מחזיר רשימת פוזיציות פתוחות מחשבון Binance Futures.
    אם אין פוזיציות → מחזיר [].
    """
    try:
        positions = futures_open_positions()
        if not positions:
            return []
        # ניקוי/המרה לשדות רלוונטיים בלבד
        clean = []
        for p in positions:
            clean.append({
                "symbol": p.get("symbol"),
                "positionAmt": p.get("positionAmt"),
                "entryPrice": p.get("entryPrice"),
                "unRealizedProfit": p.get("unRealizedProfit"),
                "leverage": p.get("leverage"),
                "marginType": p.get("marginType"),
            })
        return clean
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch open positions: {e}")

@router.get("/status")
def executor_status() -> Dict[str, Any]:
    """
    מחזיר סטטוס בסיסי של ה־Executor.
    """
    return {
        "ok": True,
        "executor": "running",
        "positions_endpoint": "/executor/positions",
    }

















