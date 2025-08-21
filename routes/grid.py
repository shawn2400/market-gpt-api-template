# routes/grid.py
from fastapi import APIRouter
from pydantic import BaseModel
from typing import List
from utils.grid_manager import get_grid_status, get_active_grids

router = APIRouter()

class GridStatus(BaseModel):
    id: str
    symbol: str
    levels: int
    allocated: float
    profit_pct: float
    active: bool

@router.get("/status", response_model=List[GridStatus])
async def grid_status():
    grids = get_grid_status()
    return [GridStatus(**g) for g in grids]

@router.get("/active", response_model=List[GridStatus])
async def active_grids():
    return [GridStatus(**g) for g in get_active_grids()]













