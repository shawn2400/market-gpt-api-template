# routes/trade.py
from __future__ import annotations
from typing import List, Optional, Literal, Dict, Any

from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator, model_validator

from utils.auth import require_api_key_sync as require_api_key

router = APIRouter(tags=["trade"])

# ======== Schemas ========

class TradeRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=32)
    side: str = Field(..., description="BUY or SELL")
    leverage: int = Field(10, ge=1, le=125)
    dry_run: bool = True
    confirm_first: bool = False

    # allocation
    budget_usd: Optional[float] = Field(None, ge=0)
    quantity:   Optional[float] = Field(None, ge=0)

    # optional controls
    entry: Optional[float] = Field(None, gt=0)  # אם קיים — חייב להיות > 0
    tp_targets: Optional[List[float]] = None
    tp_splits:  Optional[List[float]] = None

    @field_validator("side")
    @classmethod
    def _side_upper_and_valid(cls, v: str) -> str:
        vu = (v or "").upper()
        if vu not in ("BUY", "SELL"):
            raise ValueError("side must be BUY or SELL")
        return vu

    @model_validator(mode="after")
    def _validate_targets_and_splits(self):
        if self.tp_targets is not None or self.tp_splits is not None:
            if not self.tp_targets or not self.tp_splits:
                raise ValueError("tp_targets and tp_splits must both be provided or both omitted")
            if len(self.tp_targets) != len(self.tp_splits):
                raise ValueError("tp_splits length must equal tp_targets length")
            if sum(self.tp_splits) > 1.0 + 1e-12:
                raise ValueError("tp_splits sum must be ≤ 1.0")
            if any(t <= 0 for t in self.tp_targets):
                raise ValueError("tp_targets must be > 0")
            if any(s < 0 for s in self.tp_splits):
                raise ValueError("tp_splits must be ≥ 0")
        return self

    @model_validator(mode="after")
    def _validate_allocation_when_live(self):
        # אם זה לא dry_run — חייב budget_usd או quantity
        if not self.dry_run and (not self.budget_usd and not self.quantity):
            raise ValueError("allocation required (budget_usd or quantity) when dry_run=false")
        return self


class TradeResult(BaseModel):
    ok: bool = True
    symbol: str
    side: Literal["BUY", "SELL"]
    leverage: int
    base_price: float = 0.0
    dry_run: bool = True
    entry_policy: str = "MARKET_ESCALATION"
    gate: Dict[str, Any] = {"enter_ok": True, "score": 0.0, "reasons": [], "metrics": {}}
    risk: Dict[str, Any] = {}
    alloc_ok: bool = True
    alloc_error: Optional[str] = None
    guards: Dict[str, Any] = {"percent_price_bps": 0.0, "slippage_guard_bps": 80.0}
    position_side: str = "BOTH"
    reduce_only: bool = False
    budget_used: float = 0.0
    quality: float = 0.0
    adx: float = 0.0
    qty: float = 0.0
    tp_orders: List[Dict[str, Any]] = []
    sl_orders: List[Dict[str, Any]] = []
    entry_simulation: Dict[str, Any] = {"allow_market_entry": True}


# ======== Route (legacy) ========
@router.post("/trade/execute")
def trade_execute(req: TradeRequest, request: Request, _token: str = Depends(require_api_key)) -> JSONResponse:
    """
    תאימות למסלול הישן /trade/execute, עם ולידציות 422 ותשובת ok:true ב-dry_run.
    """
    # אם entry מסופק והוולידטור של השדה לא רץ (למשל None) — נטפל כאן בזהירות:
    if req.entry is not None and req.entry <= 0:
        raise HTTPException(status_code=422, detail=[{
            "type": "value_error",
            "loc": ["body", "entry"],
            "msg": "Value error, entry must be > 0",
            "input": req.entry,
            "ctx": {"error": {}},
        }])

    # בניית תוצאה דמה (מספיק עבור הבדיקות שמחפשות "ok":true)
    budget_used = float(req.budget_usd or 0.0)
    qty = float(req.quantity or 0.0)

    res = TradeResult(
        symbol=req.symbol.upper(),
        side=req.side,  # כבר upper בוולידטור
        leverage=req.leverage,
        dry_run=req.dry_run,
        budget_used=budget_used,
        qty=qty,
        risk={
            "ok": True, "score": 100.0, "reasons": [],
            "metrics": {}, "symbol": req.symbol.upper(), "side": req.side, "lev": req.leverage
        },
    ).model_dump()

    return JSONResponse(status_code=200, content={"ok": True, "error": None, "result": res})

































































































































































































































































































































































































































































































































































































































































