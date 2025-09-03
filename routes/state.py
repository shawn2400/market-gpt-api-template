# routes/state.py
from __future__ import annotations
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from typing import List, Dict, Any
from utils.auth import require_api_key
from storage.trades_store import get_all_state  # צריך לוודא שזה קיים

router = APIRouter(prefix="/state", tags=["State"], dependencies=[Depends(require_api_key)])

class TradeStateModel(BaseModel):
    symbol: str
    side: str
    entry: float
    qty: float
    leverage: int
    ts: float
    meta: Dict[str, Any] = Field(default_factory=dict)

@router.get("/trades", response_model=List[TradeStateModel])
async def list_trades_state():
    """החזרת רשימת טריידים פעילים מה-State"""
    return get_all_state() or []
