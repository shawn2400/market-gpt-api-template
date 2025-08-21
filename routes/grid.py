from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from typing import List, Dict, Any
from utils.grid_manager import get_grid_status, get_active_grids

router = APIRouter(tags=["Grid"])

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












