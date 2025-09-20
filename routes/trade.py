# routes/trade.py
from __future__ import annotations
import time, secrets
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
import httpx

from utils.auth import require_api_key

try:
    from utils.telegram_notifier import send_approval, send_audit  # type: ignore
except Exception:
    async def send_approval(*args, **kwargs):  # type: ignore
        return None
    async def send_audit(*args, **kwargs):  # type: ignore
        return None

try:
    from utils.approval_rules import should_auto_approve  # type: ignore
except Exception:
    def should_auto_approve(payload: Dict[str, Any]):  # type: ignore
        return (False, "rules_missing")

try:
    from utils.trade_executor import execute_trade_live  # type: ignore
except Exception:
    execute_trade_live = None  # type: ignore

router = APIRouter(tags=["trade"])

_PENDING: Dict[str, Dict[str, Any]] = {}
_PENDING_TTL = 60 * 5

def _make_idem(x: Optional[str]) -> str:
    return x or f"{int(time.time()*1000)}_{secrets.token_hex(6)}"

class TradeReq(BaseModel):
    symbol: str
    side: str
    leverage: int = Field(ge=1, le=125)
    budget_usd: float = Field(gt=0)
    dry_run: bool = False
    confirm_first: bool = False
    entry: Optional[float] = None
    tp_targets: Optional[List[float]] = None
    tp_splits: Optional[List[float]] = None

    @field_validator("side")
    @classmethod
    def _side_ok(cls, v: str) -> str:
        if v.upper() not in ("BUY","SELL"):
            raise ValueError("side must be BUY or SELL")
        return v

    @field_validator("tp_splits")
    @classmethod
    def _splits_sum_ok(cls, v: Optional[List[float]]):
        if v is not None and sum(v) > 1.0 + 1e-9:
            raise ValueError("sum(tp_splits) must be <= 1")
        return v

def _422(detail: Any) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail)

def _summary(req: TradeReq) -> str:
    return f"{req.side.upper()} {req.symbol.upper()} lev={req.leverage} budget=${req.budget_usd} dry={req.dry_run}"

async def _execute_and_audit(req: TradeReq) -> Dict[str, Any]:
    if execute_trade_live is None:
        raise RuntimeError("trade executor missing")
    res = await execute_trade_live(
        symbol=req.symbol,
        market="futures",
        side=req.side,
        entry="market" if (req.entry is None) else "limit",
        entry_price=req.entry if (req.entry and req.entry > 0) else None,
        budget_usdt=req.budget_usd,
        leverage=req.leverage,
        risk_pct=None,
        stop_loss_pct=None,
        take_profit_rr=None,
        require_approval=False,
        reason="trade_execute_api",
    )
    await send_audit("TRADE EXECUTE API", {
        "symbol": req.symbol,
        "side": req.side,
        "lev": req.leverage,
        "budget": req.budget_usd,
        "dry": req.dry_run,
        "entry": req.entry,
    })
    return res

@router.post("/trade/execute")
async def trade_execute(
    req: TradeReq,
    request: Request,
    _token: str = Depends(require_api_key),
    x_idem: Optional[str] = Header(default=None, alias="X-Idempotency-Key"),
) -> Dict[str, Any]:
    if req.entry is not None and req.entry < 0:
        raise _422([{"type":"value_error","loc":["body","entry"],"msg":"entry must be >= 0","input": req.entry}])

    idem = _make_idem(x_idem)
    auto, reason = should_auto_approve(req.model_dump())
    need_approval = bool(req.confirm_first and not req.dry_run and not auto)

    if need_approval:
        _PENDING[idem] = {"ts": time.time(), "req": req.model_dump()}
        try:
            await send_approval(idem, _summary(req))
        except Exception:
            pass
        return {"ok": False, "error": "pending_approval", "result": {"reason": "pending", "idem": idem, "ttl_sec": _PENDING_TTL}}

    try:
        res = await _execute_and_audit(req)
        if auto and not req.dry_run:
            await send_audit("AUTO-APPROVED", {"idem": idem, "reason": reason})
        return {"ok": True, "error": None, "result": res}
    except ValueError as ve:
        raise _422([{"type":"value_error","loc":["body"],"msg":str(ve)}])
    except httpx.HTTPStatusError as he:
        raise HTTPException(status_code=502, detail={"error":"binance_http", "status": he.response.status_code, "body": he.response.text})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/trade/approve", include_in_schema=False)
async def trade_approve(id: str, _token: str = Depends(require_api_key)) -> Dict[str, Any]:
    item = _PENDING.pop(id, None)
    if not item:
        return {"ok": False, "error": "not_found_or_expired"}
    req = TradeReq(**item["req"])
    try:
        res = await _execute_and_audit(req)
        return {"ok": True, "result": res}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@router.get("/trade/reject", include_in_schema=False)
async def trade_reject(id: str, _token: str = Depends(require_api_key)) -> Dict[str, Any]:
    _PENDING.pop(id, None)
    await send_audit("REJECTED", {"idem": id})
    return {"ok": True, "rejected": True}

class MarketOpenReq(BaseModel):
    symbol: str
    market: str = "futures"
    side: str   = Field(pattern="^(BUY|SELL|LONG|SHORT)$")
    budget_usd: Optional[float] = 50.0
    leverage: int = Field(default=10, ge=1, le=125)
    dry_run: bool = False
    confirm_first: bool = False
    reason: Optional[str] = None

@router.post("/trade/market/open")
async def trade_market_open(req: MarketOpenReq, _token: str = Depends(require_api_key)):
    tr = TradeReq(
        symbol=req.symbol,
        side=("BUY" if req.side.upper() in ("BUY","LONG") else "SELL"),
        leverage=req.leverage,
        budget_usd=(req.budget_usd or 50.0),
        dry_run=req.dry_run,
        confirm_first=req.confirm_first,
        entry=None,
        tp_targets=None, tp_splits=None
    )
    res = await _execute_and_audit(tr)
    await send_audit("MARKET_OPEN", {"symbol": tr.symbol, "side": tr.side, "budget": tr.budget_usd, "reason": req.reason or "api_market_open"})
    return {"ok": True, "result": res}







































































































































































































































































































































































































































































































































































































































































