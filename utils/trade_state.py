# utils/trade_state.py
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
import uuid

class TradeState(str, Enum):
    NEW = "NEW"
    SUBMITTED = "SUBMITTED"            # נפתחו פקודות כניסה/סטופ/טי.פי
    WORKING = "WORKING"                # הפקודות בתוקף, ממתין למילוי
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"                  # כניסה מלאה
    TP1 = "TP1"
    TP2 = "TP2"
    EXITED = "EXITED"                  # נסגר ברווח
    STOPPED = "STOPPED"                # נסגר בסטופ
    CANCELED = "CANCELED"
    ERROR = "ERROR"

_ALLOWED: Dict[TradeState, set[TradeState]] = {
    TradeState.NEW: {TradeState.SUBMITTED, TradeState.CANCELED, TradeState.ERROR},
    TradeState.SUBMITTED: {TradeState.WORKING, TradeState.CANCELED, TradeState.ERROR},
    TradeState.WORKING: {TradeState.PARTIALLY_FILLED, TradeState.FILLED, TradeState.CANCELED, TradeState.ERROR},
    TradeState.PARTIALLY_FILLED: {TradeState.FILLED, TradeState.CANCELED, TradeState.ERROR},
    TradeState.FILLED: {TradeState.TP1, TradeState.TP2, TradeState.EXITED, TradeState.STOPPED, TradeState.ERROR},
    TradeState.TP1: {TradeState.TP2, TradeState.EXITED, TradeState.STOPPED, TradeState.ERROR},
    TradeState.TP2: {TradeState.EXITED, TradeState.STOPPED, TradeState.ERROR},
    TradeState.EXITED: set(),
    TradeState.STOPPED: set(),
    TradeState.CANCELED: set(),
    TradeState.ERROR: set(),
}

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

@dataclass
class Trade:
    trade_id: str
    symbol: str
    side: str                     # "LONG" / "SHORT"
    qty: float
    entry_price: Optional[float] = None
    stop_price: Optional[float] = None
    tp_prices: List[float] = field(default_factory=list)
    state: TradeState = TradeState.NEW
    filled_qty: float = 0.0
    realized_pnl: float = 0.0
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)
    meta: Dict[str, Any] = field(default_factory=dict)

    def can_transition(self, to: TradeState) -> bool:
        return to in _ALLOWED.get(self.state, set())

    def set_state(self, to: TradeState) -> None:
        if not self.can_transition(to):
            raise ValueError(f"illegal transition {self.state} -> {to}")
        self.state = to
        self.updated_at = _now_iso()

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["state"] = self.state.value
        return d

def new_trade_id(prefix: str = "T") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"

__all__ = ["TradeState", "Trade", "new_trade_id"]
