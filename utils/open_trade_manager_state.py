# -*- coding: utf-8 -*-
# utils/open_trade_manager_state.py
from __future__ import annotations
import time, logging
from dataclasses import dataclass, field
from typing import Dict, Any, Optional
from contextlib import suppress

log = logging.getLogger("algogpt.open_trade_manager_state")

# Optional external helpers (if present we’ll use them; else provide shims)
try:
    from utils.order_hygiene import (  # type: ignore
        place_limit_order_safe,
        place_stop_market_safe,
        place_take_profit_safe,
        cancel_if_conflict,
        check_minimums,
    )
    _HAS_HYGIENE = True
except Exception:
    _HAS_HYGIENE = False

    def cancel_if_conflict(symbol: str, side: str) -> None:
        log.info("cancel_if_conflict(shim): %s %s", symbol, side)

    def check_minimums(symbol: str, qty: float) -> bool:
        ok = (symbol and (qty or 0) > 0)
        if not ok:
            log.warning("check_minimums(shim) failed: symbol=%s qty=%s", symbol, qty)
        return ok

    def place_limit_order_safe(**kw) -> Dict[str, Any]:
        return {"ok": True, "response": {"orderId": f"SIM-LMT-{int(time.time()*1000)}", "echo": kw}}

    def place_stop_market_safe(**kw) -> Dict[str, Any]:
        return {"ok": True, "response": {"orderId": f"SIM-SL-{int(time.time()*1000)}", "echo": kw}}

    def place_take_profit_safe(**kw) -> Dict[str, Any]:
        return {"ok": True, "response": {"orderId": f"SIM-TP-{int(time.time()*1000)}", "echo": kw}}

# PnL/ROE snapshot (if available)
with suppress(Exception):
    from utils.binance_trade import unrealized as pnl_snapshot, _side_dir  # type: ignore
except Exception:
    def pnl_snapshot(symbol: str) -> Dict[str, Any]:
        return {"ok": False, "error": "pnl_snapshot_missing"}
    def _side_dir(side: str) -> int:
        s = (side or "").upper()
        if s in ("BUY","LONG"): return +1
        if s in ("SELL","SHORT"): return -1
        return 0

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
    time_stop_sec: Optional[int] = None # optional time stop
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
    Lightweight state machine for open-trade bootstrap & early management.
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

    # ── INIT ──────────────────────────────────────────────────────────────────
    def _step_init(self) -> Dict[str, Any]:
        p = self.plan

        if p.entry_price is None:
            return {"ok": False, "state": "INIT", "error": "missing_entry_price"}
        if p.sl_price is None:
            return {"ok": False, "state": "INIT", "error": "missing_sl_price"}
        if p.tp_price is None:
            return {"ok": False, "state": "INIT", "error": "missing_tp_price"}

        try:
            cancel_if_conflict(p.symbol, p.side)
        except Exception as e:
            log.warning("cancel_if_conflict failed: %s", e)

        if not check_minimums(p.symbol, float(p.qty)):
            return {"ok": False, "state": "INIT", "error": "min_check_failed"}

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

        self.state.name = "ACTIVE"
        self.state.entry_order_id = str(entry.get("orderId") or entry.get("response", {}).get("orderId") or "")
        self.state.sl_order_id    = str(sl.get("orderId")    or sl.get("response", {}).get("orderId")    or "")
        self.state.tp_order_id    = str(tp.get("orderId")    or tp.get("response", {}).get("orderId")    or "")
        self.state.last_action_ts = time.time()

        return {"ok": True, "state": "ACTIVE", "entry": entry, "sl": sl, "tp": tp, "hygiene_impl": _HAS_HYGIENE}

    # ── ACTIVE ────────────────────────────────────────────────────────────────
    def _step_active(self) -> Dict[str, Any]:
        self.state.name = "MANAGE"
        self.state.last_action_ts = time.time()
        return {"ok": True, "state": "MANAGE", "note": "promoted_to_manage"}

    # ── MANAGE ────────────────────────────────────────────────────────────────
    def _step_manage(self) -> Dict[str, Any]:
        p = self.plan
        now = time.time()

        if p.time_stop_sec and (now - p.created_ts) >= int(p.time_stop_sec):
            self.state.name = "EXIT"
            self.state.last_action_ts = now
            return {"ok": True, "state": "EXIT", "reason": "time_stop"}

        # passive (can be extended to trailing/BE logic)
        return {"ok": True, "state": "MANAGE", "note": "idle"}

    # ── Brief status line (he/en mix) ─────────────────────────────────────────
    def brief_status(self) -> str:
        """
        Returns a short he/en mixed status string for chat/telemetry.
        Example:
        'BTCUSDT LONG qty=0.001 | PnL=+0.43% (ROE +6.5%) | ETA: TP1~5m TP2~15m TP3~30m'
        """
        p = self.plan
        snap = pnl_snapshot(p.symbol)
        pnl_s = "PnL=0.00%"
        roe_s = ""
        if snap.get("ok") and not snap.get("empty"):
            pnl_s = f"PnL={snap.get('pnl_pct',0.0):+0.2f}%"
            roe = snap.get("roe_pct", 0.0)
            roe_s = f" (ROE {roe:+0.1f}%)"
        eta = p.meta.get("eta", {"tp1_sec": 300, "tp2_sec": 900, "tp3_sec": 1800})
        def _mins(s): 
            try: return f"{int(round(float(s)/60))}m"
            except Exception: return "?"
        eta_s = f"ETA: TP1~{_mins(eta.get('tp1_sec',300))} TP2~{_mins(eta.get('tp2_sec',900))} TP3~{_mins(eta.get('tp3_sec',1800))}"
        return f"{p.symbol} {'LONG' if _side_dir(p.side)>0 else 'SHORT'} qty={p.qty} | {pnl_s}{roe_s} | {eta_s}"



