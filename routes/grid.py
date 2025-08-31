from __future__ import annotations
from fastapi import APIRouter, Depends
from typing import Dict, Any
from utils.auth import require_api_key

router = APIRouter(prefix="/grid", tags=["Grid"], dependencies=[Depends(require_api_key)])

@router.get("/status")
def grid_status() -> Dict[str, Any]:
    return {"ok": True, "grid_enabled": True, "active_strategies": 0, "note": "Grid engine loaded, no active grids"}

@router.get("/active")
def grid_active() -> Dict[str, Any]:
    return {"ok": True, "active": []}

@router.post("/start")
def grid_start() -> Dict[str, Any]:
    return {"ok": True, "message": "Grid start requested"}

@router.post("/stop")
def grid_stop() -> Dict[str, Any]:
    return {"ok": True, "message": "Grid stop requested"}















