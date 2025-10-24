# schemas/manage_state.py
from __future__ import annotations

from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field


class TradeStateItem(BaseModel):
    trade_id: str = Field(default="")
    symbol: str = Field(default="")
    side: str = Field(default="")
    qty: float = Field(default=0.0)
    leverage: int = Field(default=0)
    state: str = Field(default="UNKNOWN")
    entry: Optional[float] = Field(default=None)
    opened_ts: Optional[float] = Field(default=None)
    extra: Optional[Dict[str, Any]] = Field(default=None)

    class Config:
        extra = "ignore"


class TradesStateOut(BaseModel):
    ok: bool = True
    count: int
    items: List[TradeStateItem]

    class Config:
        extra = "ignore"


__all__ = ["TradeStateItem", "TradesStateOut"]
