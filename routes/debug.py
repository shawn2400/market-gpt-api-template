# routes/grid.py
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from typing import Dict, Any
from utils.auth import require_api_key

router = APIRouter(
    prefix="/grid",
    tags=["Grid"],
    dependencies=[Depends(require_api_key)]
)

@router.get("/status")
def grid_status() -> Dict[str, Any]:
    """
    סטטוס מערכת ה־Grid.
    כרגע ריק (אין אסטרטגיות פעילות), אבל אפשר להרחיב בהמשך.
    """
    try:
        return {
            "ok": True,
            "grid_enabled": True,
            "active_strategies": 0,
            "note": "Grid engine is loaded but no active grids"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Grid status error: {e}")

@router.get("/active")
def grid_active() -> Dict[str, Any]:
    """
    רשימת גרידים פעילים (כרגע ריק).
    אפשר להרחיב בהמשך למידע על אסטרטגיות פעילות.
    """
    try:
        return {"ok": True, "active": []}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Grid active error: {e}")





