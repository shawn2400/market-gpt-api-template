# /app/routes/executor.py
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, conint, confloat, model_validator

from utils.auth import require_api_key

router = APIRouter(prefix="/executor", tags=["executor"])

# --- Idempotency (in-memory, TTL~15s) ---
_IDEM_STORE: Dict[str, float] = {}
_IDEM_TTL_SEC = 15.0

def _idem_check_and_set(key: Optional[str]) -> Optional[str]:
    if not key:
        return None
    now = time.time()
    # purge
    for k, t in list(_IDEM_STORE.items()):
        if t < now:
            _IDEM_STORE.pop(k, None)
    if key in _IDEM_STORE:
        return "idem_conflict"
    _IDEM_STORE[key] = now + _IDEM_TTL_SEC
    return None

# ---------- Public: health / status ----------

@router.get("/status")
def executor_status() -> Dict[str, Any]:
    """Public liveness endpoint (מוגדר כ-public דרך SECURITY_PUBLIC_PATHS)."""
    return {
        "ok": True,
        "status": "running",
        "ts": int(time.time() * 1000),
    }

# ---------- Protected endpoints (need API key) ----------

@router.get("/positions")
def get_positions(_: str = Depends(require_api_key)) -> Dict[str, Any]:
    """Return current positions list (דמה)."""
    return {"ok": True, "positions": []}

@router.get("/balance")
def get_balance(_: str = Depends(require_api_key)) -> Dict[str, Any]:
    """Return wallet / margin balances (דמה)."""
    return {"ok": True, "balances": []}

# ---------- Trade model & logic (דמה) ----------

class TradeRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=32)
    side: Literal["BUY", "SELL"]  # יתקבל גם lowercase ע"י הממיר למטה
    leverage: conint(ge=1, le=125) = 1
    budget_usd: Optional[confloat(gt=0)] = None
    quantity: Optional[confloat(gt=0)] = None
    dry_run: bool = True
    confirm_first: bool = False
    entry: Optional[confloat(gt=0)] = None
    tp_targets: Optional[List[confloat(gt=0)]] = None
    tp_splits: Optional[List[confloat(gt=0)]] = None

    @model_validator(mode="before")
    @classmethod
    def _coerce_side(cls, data):
        if isinstance(data, dict) and "side" in data and isinstance(data["side"], str):
            data["side"] = data["side"].upper()
        return data

    @model_validator(mode="after")
    def _business_rules(self):
        # אם לא dry_run — חייב allocation
        if not self.dry_run and not (self.budget_usd or self.quantity):
            raise ValueError("allocation (budget_usd or quantity) is required when dry_run=false")

        # אם יש targets/splits — אורך תואם וסכום <= 1.0
        if self.tp_targets is not None or self.tp_splits is not None:
            if not self.tp_targets or not self.tp_splits:
                raise ValueError("tp_targets and tp_splits must be provided together")
            if len(self.tp_targets) != len(self.tp_splits):
                raise ValueError("tp_targets and tp_splits must have equal length")
            if sum(self.tp_splits) > 1.0 + 1e-9:
                raise ValueError("tp_splits sum must be <= 1.0")

        return self

@router.post("/trade")
def trade(
    req: TradeRequest,
    request: Request,
    _token: str = Depends(require_api_key),
    x_idempotency_key: Optional[str] = Header(default=None, alias="X-Idempotency-Key"),
) -> Dict[str, Any]:
    """
    סימולציית טרייד (דמה) עם ולידציות מלאות + Idempotency (409) + החזרי 422 נכונים.
    """
    # Idempotency
    conflict = _idem_check_and_set(x_idempotency_key)
    if conflict:
        # שמור 409 רק להתנגשות Idempotency — זה מאפשר להבדיל משגיאות 422.
        return JSONResponse(
            status_code=409,
            content={"ok": False, "error": conflict, "result": {"ok": False, "reason": conflict, "ttl_sec": int(_IDEM_TTL_SEC)}},
        )

    # Business logic (דמה)
    side_up = req.side
    base_price = 0.0  # אפשר להחליף ל-/price/<symbol> אם תרצה
    result = {
        "ok": True,
        "symbol": req.symbol,
        "side": side_up,
        "leverage": req.leverage,
        "base_price": base_price,
        "dry_run": req.dry_run,
        "entry_policy": "MARKET_ESCALATION",
        "gate": {"enter_ok": True, "score": 0.0, "reasons": [], "metrics": {}},
        "risk": {"ok": True, "score": 100.0, "reasons": [], "metrics": {}, "symbol": req.symbol, "side": side_up, "lev": req.leverage},
        "alloc_ok": True,
        "alloc_error": None,
        "guards": {"percent_price_bps": 0.0, "slippage_guard_bps": 80.0},
        "position_side": "BOTH",
        "reduce_only": False,
        "budget_used": float(req.budget_usd or 0.0),
        "quality": 0.0,
        "adx": 0.0,
        "qty": float(req.quantity or 0.0),
        "tp_orders": [],
        "sl_orders": [],
        "entry_simulation": {"allow_market_entry": True},
    }
    return {"ok": True, "result": result}














