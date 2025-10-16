# utils/open_trade_manager_state.py
from __future__ import annotations
import time
import logging
from dataclasses import dataclass, field
from typing import Dict, Any, Optional

from utils.order_hygiene import (
    place_limit_order_safe,
    place_stop_market_safe,
    place_take_profit_safe,
    cancel_if_conflict,
    check_minimums,
)

log = logging.getLogger("algogpt.open_trade_manager_state")


@dataclass
class TradePlan:
    symbol: str
    side: str  # BUY/SELL
    qty: float
    entry_price: float
    sl_price: float
    tp_price: float
    leverage: int = 10
    position_side: str = "BOTH"
    time_stop_sec: Optional[int] = None  # אם מוגדר – ייסגר מנהלית אחרי פרק זמן
    created_ts: float = field(default_factory=lambda: time.time())


@dataclass
class TradeState:
    name: str = "INIT"
    entry_order_id: Optional[str] = None
    sl_order_id: Optional[str] = None
    tp_order_id: Optional[str] = None
    last_action_ts: float = field(default_factory=lambda: time.time())
    entered: bool = False


class TradeStateManager:
    """
    State Machine רזה: INIT -> ACTIVE -> MANAGE -> EXIT
    - INIT: ביטול קונפליקטים + בדיקות מינימום + Entry/SL/TP
    - ACTIVE: אחרי יצירה מוצלחת, מאפשר מעבר לניהול
    - MANAGE: מקום ל-hooks (anti-stale nudges / merge/rearm / profit-lock)
    - EXIT: יציאה נקייה (כאן רק מסמן – בפועל סגירה מתבצעת מחוץ למחלקה)
    """

    def __init__(self, plan: TradePlan):
        self.plan = plan
        self.state = TradeState()

    def _ok(self, resp: Dict[str, Any]) -> bool:
        return bool(resp and (resp.get("ok") is True or "orderId" in resp or "clientOrderId" in resp))

    def run_once(self) -> Dict[str, Any]:
        if self.state.name == "EXIT":
            return {"ok": True, "state": "EXIT", "note": "already finished"}

        if self.state.name == "INIT":
            return self._step_init()

        if self.state.name == "ACTIVE":
            return self._step_active()

        if self.state.name == "MANAGE":
            return self._step_manage()

        # Unknown
        return {"ok": False, "state": self.state.name, "error": "unknown_state"}

    # ──────────────────────────────────────────────────────────────────────────
    # INIT
    # ──────────────────────────────────────────────────────────────────────────
    def _step_init(self) -> Dict[str, Any]:
        p = self.plan
        # ניקוי קונפליקטים
        cancel_if_conflict(p.symbol, p.side)

        # מינימום
        if not check_minimums(p.symbol, float(p.qty)):
            return {"ok": False, "state": "INIT", "error": "min_check_failed"}

        # ENTRY
        entry = place_limit_order_safe(
            symbol=p.symbol,
            side=p.side,
            quantity=str(p.qty),
            price=str(p.entry_price),
            reduce_only=False,
            position_side=p.position_side,
        )
        if not self._ok(entry):
            return {"ok": False, "state": "INIT", "error": "entry_failed", "detail": entry}

        # SL
        sl = place_stop_market_safe(
            symbol=p.symbol,
            side="SELL" if p.side.upper() == "BUY" else "BUY",
            quantity=str(p.qty),
            stop_price=str(p.sl_price),
            reduce_only=True,
            position_side=p.position_side,
        )
        if not self._ok(sl):
            return {"ok": False, "state": "INIT", "error": "sl_failed", "detail": sl}

        # TP
        tp = place_take_profit_safe(
            symbol=p.symbol,
            side="SELL" if p.side.upper() == "BUY" else "BUY",
            quantity=str(p.qty),
            tp_price=str(p.tp_price),
            reduce_only=True,
            position_side=p.position_side,
        )
        if not self._ok(tp):
            return {"ok": False, "state": "INIT", "error": "tp_failed", "detail": tp}

        self.state.name = "ACTIVE"
        self.state.entry_order_id = str(entry.get("orderId") or entry.get("response", {}).get("orderId") or "")
        self.state.sl_order_id = str(sl.get("orderId") or sl.get("response", {}).get("orderId") or "")
        self.state.tp_order_id = str(tp.get("orderId") or tp.get("response", {}).get("orderId") or "")
        self.state.last_action_ts = time.time()

        return {"ok": True, "state": "ACTIVE", "entry": entry, "sl": sl, "tp": tp}

    # ──────────────────────────────────────────────────────────────────────────
    # ACTIVE
    # ──────────────────────────────────────────────────────────────────────────
    def _step_active(self) -> Dict[str, Any]:
        # כאן אפשר לשלב בדיקות “האם נכנסנו בפועל”, אך לשם פשטות ממשיכים ל-MANAGE
        self.state.name = "MANAGE"
        self.state.last_action_ts = time.time()
        return {"ok": True, "state": "MANAGE", "note": "promoted_to_manage"}

    # ──────────────────────────────────────────────────────────────────────────
    # MANAGE
    # ──────────────────────────────────────────────────────────────────────────
    def _step_manage(self) -> Dict[str, Any]:
        p = self.plan
        now = time.time()

        # Time-Stop (אופציונלי)
        if p.time_stop_sec and (now - p.created_ts) >= int(p.time_stop_sec):
            self.state.name = "EXIT"
            self.state.last_action_ts = now
            return {"ok": True, "state": "EXIT", "reason": "time_stop"}

        # המקום ל־hooks עתידיים:
        # - anti-stale nudges
        # - profit-lock bands
        # - merge/rearm
        # כעת נעשה no-op ונחזיר סטטוס תקין.
        return {"ok": True, "state": "MANAGE", "note": "idle"}

