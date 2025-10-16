הנה גרסה תקינה להעתקה:

```python
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
    side: str                  # BUY / SELL
    qty: float
    entry_price: Optional[float] = None
    sl_price: Optional[float] = None
    tp_price: Optional[float] = None
    leverage: int = 10
    position_side: str = "BOTH"         # LONG/SHORT/BOTH
    time_stop_sec: Optional[int] = None # זמן-עצירה מנהלי (אופציונלי)
    meta: Dict[str, Any] = field(default_factory=dict)
    created_ts: float = field(default_factory=lambda: time.time())


@dataclass
class TradeState:
    name: str = "INIT"                   # INIT→ACTIVE→MANAGE→EXIT
    entry_order_id: Optional[str] = None
    sl_order_id: Optional[str] = None
    tp_order_id: Optional[str] = None
    last_action_ts: float = field(default_factory=lambda: time.time())
    entered: bool = False


class TradeStateManager:
    """
    State Machine רזה לפתיחה וניהול ראשוני של טרייד:
      INIT  : ניקוי קונפליקטים, בדיקות מינימום, יצירת ENTRY/SL/TP
      ACTIVE: אחרי יצירה מוצלחת, מקדם ל-MANAGE
      MANAGE: הוקס עתידיים (anti-stale / merge/rearm / profit-lock)
      EXIT  : יציאה נקייה (סימון סיום — הסגירה בפועל מחוץ למחלקה)
    """

    def __init__(self, plan: TradePlan):
        self.plan = plan
        self.state = TradeState()

    @staticmethod
    def _ok(resp: Dict[str, Any]) -> bool:
        if not resp:
            return False
        if resp.get("ok") is True:
            return True
        # תמיכה בתשובות SDK שונות
        if any(k in resp for k in ("orderId", "clientOrderId", "response")):
            return True
        return False

    def run_once(self) -> Dict[str, Any]:
        if self.state.name == "EXIT":
            return {"ok": True, "state": "EXIT", "note": "already_finished"}

        if self.state.name == "INIT":
            return self._step_init()
        if self.state.name == "ACTIVE":
            return self._step_active()
        if self.state.name == "MANAGE":
            return self._step_manage()

        return {"ok": False, "state": self.state.name, "error": "unknown_state"}

    # ───────────────────────── INIT ─────────────────────────
    def _step_init(self) -> Dict[str, Any]:
        p = self.plan

        # 0) ולידציה בסיסית לשדות האופציונליים שנדרשים לפתיחה
        if p.entry_price is None:
            return {"ok": False, "state": "INIT", "error": "missing_entry_price"}
        if p.sl_price is None:
            return {"ok": False, "state": "INIT", "error": "missing_sl_price"}
        if p.tp_price is None:
            return {"ok": False, "state": "INIT", "error": "missing_tp_price"}

        # 1) ניקוי קונפליקטים (SL/Trail/TPS ישנים)
        try:
            cancel_if_conflict(p.symbol, p.side)
        except Exception as e:
            log.warning("cancel_if_conflict failed: %s", e)

        # 2) מינימום כמות/טיק/סטפ
        if not check_minimums(p.symbol, float(p.qty)):
            return {"ok": False, "state": "INIT", "error": "min_check_failed"}

        # 3) ENTRY (LIMIT) — reduce_only=False
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

        # 4) SL (STOP_MARKET) — reduce_only=True
        sl = place_stop_market_safe(
            symbol=p.symbol,
            side=("SELL" if p.side.upper() == "BUY" else "BUY"),
            quantity=str(p.qty),
            stop_price=str(p.sl_price),
            reduce_only=True,
            position_side=p.position_side,
        )
        if not self._ok(sl):
            return {"ok": False, "state": "INIT", "error": "sl_failed", "detail": sl}

        # 5) TP (LIMIT / TAKE_PROFIT_MARKET תחת ה-wrapper) — reduce_only=True
        tp = place_take_profit_safe(
            symbol=p.symbol,
            side=("SELL" if p.side.upper() == "BUY" else "BUY"),
            quantity=str(p.qty),
            tp_price=str(p.tp_price),
            reduce_only=True,
            position_side=p.position_side,
        )
        if not self._ok(tp):
            return {"ok": False, "state": "INIT", "error": "tp_failed", "detail": tp}

        # עדכון מצב
        self.state.name = "ACTIVE"
        self.state.entry_order_id = str(entry.get("orderId") or entry.get("response", {}).get("orderId") or "")
        self.state.sl_order_id    = str(sl.get("orderId")    or sl.get("response", {}).get("orderId")    or "")
        self.state.tp_order_id    = str(tp.get("orderId")    or tp.get("response", {}).get("orderId")    or "")
        self.state.last_action_ts = time.time()

        return {"ok": True, "state": "ACTIVE", "entry": entry, "sl": sl, "tp": tp}

    # ─────────────────────── ACTIVE ───────────────────────
    def _step_active(self) -> Dict[str, Any]:
        # אפשר להוסיף פה אימות Fill בפועל; נשאיר קל:
        self.state.name = "MANAGE"
        self.state.last_action_ts = time.time()
        return {"ok": True, "state": "MANAGE", "note": "promoted_to_manage"}

    # ─────────────────────── MANAGE ───────────────────────
    def _step_manage(self) -> Dict[str, Any]:
        p = self.plan
        now = time.time()

        # Time-Stop אופציונלי
        if p.time_stop_sec and (now - p.created_ts) >= int(p.time_stop_sec):
            self.state.name = "EXIT"
            self.state.last_action_ts = now
            return {"ok": True, "state": "EXIT", "reason": "time_stop"}

        # Hooks עתידיים (anti-stale / merge / profit-lock) — כרגע no-op
        return {"ok": True, "state": "MANAGE", "note": "idle"}
```



