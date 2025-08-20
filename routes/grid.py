# routes/grid.py
from __future__ import annotations
from fastapi import APIRouter, Query
from typing import Dict, Any

router = APIRouter(prefix="/grid", tags=["Grid Trading"])

# מצב סטטי פשוט לניהול גריד
_GRID_STATUS: Dict[str, Any] = {
    "active": False,
    "symbol": None,
    "params": {},
}

@router.get("/status", summary="Get Grid Status")
async def grid_status() -> Dict[str, Any]:
    return {"ok": True, "status": _GRID_STATUS}

@router.post("/start", summary="Start Grid")
async def grid_start(symbol: str = Query(...), step: float = Query(...), qty: float = Query(...)) -> Dict[str, Any]:
    _GRID_STATUS.update({"active": True, "symbol": symbol, "params": {"step": step, "qty": qty}})
    return {"ok": True, "status": _GRID_STATUS}

@router.post("/stop", summary="Stop Grid")
async def grid_stop() -> Dict[str, Any]:
    _GRID_STATUS.update({"active": False})
    return {"ok": True, "status": _GRID_STATUS}












