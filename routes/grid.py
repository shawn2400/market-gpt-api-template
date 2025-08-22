from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from typing import List, Dict, Any
import uuid, time

from utils.grid_manager import get_grid_status, get_active_grids, add_grid, stop_grid

router = APIRouter(tags=["Grid"])

# --- Models ---

class GridStatus(BaseModel):
    id: str
    symbol: str
    levels: int
    allocated: float
    profit_pct: float
    active: bool

class GridListResponse(BaseModel):
    ok: bool = True
    count_total: int
    returned: int
    grids: List[GridStatus] = Field(default_factory=list)

class GenericResponse(BaseModel):
    ok: bool = True
    message: str = "Operation completed successfully"


# --- Endpoints ---

@router.get("/status", response_model=GridListResponse)
async def grid_status(limit: int = Query(50, ge=10, le=200), offset: int = Query(0, ge=0)):
    grids_raw: List[Dict[str, Any]] = get_grid_status() or []
    total = len(grids_raw)
    sliced = grids_raw[offset: offset + limit]
    grids = [GridStatus(**g) for g in sliced]
    return GridListResponse(count_total=total, returned=len(grids), grids=grids)


@router.get("/active", response_model=GridListResponse)
async def active_grids(limit: int = Query(50, ge=10, le=200), offset: int = Query(0, ge=0)):
    grids_raw: List[Dict[str, Any]] = get_active_grids() or []
    total = len(grids_raw)
    sliced = grids_raw[offset: offset + limit]
    grids = [GridStatus(**g) for g in sliced]
    return GridListResponse(count_total=total, returned=len(grids), grids=grids)


@router.post("/start", response_model=GenericResponse)
async def start_grid(symbol: str, levels: int = 5, allocated: float = 100.0):
    """מתחיל גריד חדש ושומר אותו בקובץ"""
    grid = {
        "id": str(uuid.uuid4()),
        "symbol": symbol.upper(),
        "levels": levels,
        "allocated": allocated,
        "profit_pct": 0.0,
        "active": True,
        "ts": int(time.time())
    }
    add_grid(grid)
    return GenericResponse(message=f"Grid started for {symbol} with {levels} levels")


@router.post("/stop", response_model=GenericResponse)
async def stop_grid_api(grid_id: str):
    """עוצר גריד לפי ID"""
    ok = stop_grid(grid_id)
    if ok:
        return GenericResponse(message=f"Grid {grid_id} stopped")
    return GenericResponse(ok=False, message=f"Grid {grid_id} not found")












