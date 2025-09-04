# routes/executor_extra.py
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from typing import Dict, Any

from utils.auth import require_api_key
from utils.binance_client import (
    get_futures_open_positions,  # alias תקין מ-binance_client
    futures_position_risk,
)

router = APIRouter(
    prefix="/executor-extra",
    tags=["Executor-Extra"],
    dependencies=[Depends(require_api_key)],
)

@router.get("/positions")
def list_positions() -> Dict[str, Any]:
    """מחזיר את כל הפוזיציות הפתוחות בחשבון."""
    try:
        positions = get_futures_open_positions() or []
        return {"ok": True, "count": len(positions), "items": positions}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"list_positions failed: {e}")

@router.get("/risk")
def list_position_risk() -> Dict[str, Any]:
    """מחזיר מידע על Position Risk."""
    try:
        risks = futures_position_risk() or []
        return {"ok": True, "count": len(risks), "items": risks}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"list_position_risk failed: {e}")






