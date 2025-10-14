# schemas/manage_state.py
from __future__ import annotations

from typing import List, Dict, Any, Optional
from pydantic import BaseModel


class TradeStateItem(BaseModel):
    trade_id: str
    symbol: str
    side: str
    qty: float
    leverage: int
    state: str
    entry: Optional[float] = None
    opened_ts: Optional[float] = None
    extra: Optional[Dict[str, Any]] = None


class TradesStateOut(BaseModel):
    ok: bool = True
    count: int
    items: List[TradeStateItem]
