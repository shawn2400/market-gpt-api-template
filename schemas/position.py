# schemas/position.py
from __future__ import annotations

from typing import Optional, List
from pydantic import BaseModel, Field


class TPLevel(BaseModel):
    price: float = Field(..., description="target price")
    split: float = Field(..., ge=0.0, le=1.0, description="fraction of position to close at this target (0..1)")


class PositionIn(BaseModel):
    symbol: str
    side: str  # BUY/SELL
    leverage: int = 10
    qty: Optional[float] = None
    budget: Optional[float] = Field(None, description="notional budget in USDT (used to size qty if qty not given)")
    position_side: Optional[str] = Field(None, description="LONG/SHORT/BOTH")
    entry: Optional[float] = None
    sl: Optional[float] = None
    tp: Optional[List[TPLevel]] = None
    note: Optional[str] = None


class PositionOut(BaseModel):
    ok: bool
    symbol: Optional[str] = None
    side: Optional[str] = None
    leverage: Optional[int] = None
    qty: Optional[float] = None
    entry: Optional[float] = None
    be_stop_price: Optional[float] = None
    tp: Optional[List[TPLevel]] = None
    trail: Optional[dict] = None
    error: Optional[str] = None
