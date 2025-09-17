# /app/routes/trade.py
from __future__ import annotations
import time
from typing import List, Optional, Dict, Any, Literal
from fastapi import APIRouter, Depends, Header, Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from utils.auth import require_api_key

router = APIRouter(tags=["trade (legacy)"])

# --- Idempotency cache (in-memory, per-worker) ---
_IDEM: Dict[str, float] = {}
_IDEM_TTL_SEC = 15.0

def _idem_check(key: Optional[str]) -> Optional[JSONResponse]:
    if not key:
        return None
    now = time.time()
    exp = _IDEM.get(key)
    if exp and exp > now:
        ttl = max(0, int(exp - now))
        return JSONResponse(
            status_code=409,
            content={"ok": False, "error": "idem_conflict", "result": {"ok": False, "reason": "idem_conflict", "ttl_sec": ttl}},
        )
    _IDEM[key] = now + _IDEM_TTL_SEC
    return None

class TradeRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=32)
    side: Literal["BUY", "SELL"]  # קלט לא רגיש רישיות → נתקן בהמשך
    leverage: int = Field(1, ge=1, le=125)
    budget_usd: Optional[float] = Field(default=None, ge=0)
    dry_run: bool = True
    confirm_first: bool = False

    # פרמטרים אופציונליים התואמים למסלול הישן
    entry: Optional[float] = Field(default=None, ge=0)
    tp_targets: Optional[List[float]] = None
    tp_splits: Optional[List[float]] = None

    @field_validator("side", mode="before")
    @classmethod
    def _side_upper(cls, v):
        if isinstance(v, str):
            v = v.strip().upper()
        if v not in ("BUY", "SELL"):
            raise ValueError("side must be BUY or SELL")
        return v

    @field_validator("tp_splits")
    @classmethod
    def _tp_sum_le_one(cls, v, info):
        # אם יש splits – סכום חייב להיות <= 1
        if v is not None:
            s = sum(v)
            if s > 1.0 + 1e-9:
                raise ValueError("tp_splits sum must be <= 1.0")
        return v

@router.post("/trade/execute")
def trade_execute(
    req: TradeRequest,
    request: Request,
    _token: str = Depends(require_api_key),
    x_idempotency_key: Optional[str] = Header(default=None, alias="X-Idempotency-Key"),
):
    # Idempotency
    idem = _idem_check(x_idempotency_key)
    if idem is not None and not req.dry_run:
        return idem  # ב-dry_run נחזיר 200 גם אם המפתח חזר—כמו ההתנהגות הקודמת

    # סימולציה פשוטה (תואם מבנה) — די למסלול הישן ולבדיקות
    base_price = 0.0
    result: Dict[str, Any] = {
        "ok": True,
        "symbol": req.symbol.upper(),
        "side": req.side,
        "leverage": req.leverage,
        "base_price": base_price,
        "dry_run": bool(req.dry_run),
        "entry_policy": "MARKET_ESCALATION",
        "gate": {"enter_ok": True, "score": 0.0, "reasons": [], "metrics": {}},
        "risk": {"ok": True, "score": 100.0, "reasons": [], "metrics": {}, "symbol": req.symbol.upper(), "side": req.side, "lev": req.leverage},
        "alloc_ok": True,
        "alloc_error": None,
        "guards": {"percent_price_bps": 0.0, "slippage_guard_bps": 80.0},
        "position_side": "BOTH",
        "reduce_only": False,
        "budget_used": float(req.budget_usd or 0.0),
        "quality": 0.0,
        "adx": 0.0,
        "qty": 0.0,
        "tp_orders": [],
        "sl_orders": [],
        "entry_simulation": {"allow_market_entry": True},
    }

    # שדות אופציונליים – ללא לוגיקה אמיתית כאן
    if req.entry is not None:
        result["entry_price"] = float(req.entry)

    return JSONResponse(status_code=200, content={"ok": True, "error": None, "result": result})


































































































































































































































































































































































































































































































































































































































































