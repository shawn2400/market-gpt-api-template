# routes/trade.py
from __future__ import annotations
import time, secrets
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
import httpx

from utils.auth import require_api_key

# ——— טלגרם: אישור דינמי + נוטיפיקציות ———
try:
    from utils.telegram_notifier import (
        send_trade_approval,   # כרטיס אישור עשיר עם כפתורים
        notify_ops_alert,      # "audit" קל
        should_auto_approve_trade,
    )  # type: ignore
except Exception:
    async def send_trade_approval(*args, **kwargs):  # type: ignore
        return None
    async def notify_ops_alert(*args, **kwargs):  # type: ignore
        return None
    def should_auto_approve_trade(payload: Dict[str, Any]) -> bool:  # type: ignore
        return False

# ——— מבצע לייב ———
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
        if v.upper() not in ("BUY", "SELL"):
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

async def _audit(tag: str, data: Dict[str, Any]) -> None:
    try:
        txt = f"{tag}: " + ", ".join(f"{k}={v}" for k, v in data.items())
        await notify_ops_alert(txt)
    except Exception:
        pass

def _gc_pending() -> None:
    now = time.time()
    dead = [k for k, v in _PENDING.items() if now - float(v.get("ts", 0)) > _PENDING_TTL]
    for k in dead:
        _PENDING.pop(k, None)

async def _execute_and_audit(req: TradeReq) -> Dict[str, Any]:
    if execute_trade_live is None:
        raise RuntimeError("trade executor missing")
    res = await execute_trade_live(
        symbol=req.symbol,
        side=req.side,
        leverage=int(req.leverage),
        budget=float(req.budget_usd),
        dry_run=bool(req.dry_run),
        entry=(float(req.entry) if (req.entry is not None and float(req.entry) > 0) else None),
        sl=None,
        tp=None,
        tp_targets=(req.tp_targets if req.tp_targets else None),
        confirm_first=False,
        telegram_chat_id=None,
    )
    await _audit("TRADE_EXECUTE_API", {
        "symbol": req.symbol, "side": req.side, "lev": req.leverage,
        "budget": req.budget_usd, "dry": req.dry_run, "entry": req.entry,
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

    _gc_pending()
    idem = _make_idem(x_idem)

    auto = bool(should_auto_approve_trade(req.model_dump()))
    need_approval = bool(req.confirm_first and not req.dry_run and not auto)

    if need_approval:
        # נשמור במאגר מקומי (מאומת ע"י /ops/approve עם חתימה)
        _PENDING[idem] = {"ts": time.time(), "req": req.model_dump()}
        # שליחת כרטיס אישור עשיר בטלגרם
        try:
            plan = {
                "symbol": req.symbol,
                "side": req.side,
                "leverage": req.leverage,
                "entry_price": req.entry,
                "tp": ([{"stopPrice": x} for x in (req.tp_targets or [])] if req.tp_targets else []),
                "budget_usd": req.budget_usd,
                "trade_kind": "Futures",
            }
            await send_trade_approval(idem, plan, chat_id=None)
        except Exception:
            pass
        return {"ok": False, "error": "pending_approval", "result": {"reason": "pending", "idem": idem, "ttl_sec": _PENDING_TTL}}

    try:
        res = await _execute_and_audit(req)
        if auto and not req.dry_run:
            await _audit("AUTO_APPROVED", {"idem": idem})
        return {"ok": True, "error": None, "result": res}
    except ValueError as ve:
        raise _422([{"type":"value_error","loc":["body"],"msg":str(ve)}])
    except httpx.HTTPStatusError as he:
        raise HTTPException(status_code=502, detail={"error":"binance_http", "status": he.response.status_code, "body": he.response.text})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# שימו לב: ה־URLs הפומביים לאישור מגיעים דרך /ops/approve (ללא API Key).
# אלו נשארים לשימוש פנימי/ידני בלבד.

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
    await _audit("REJECTED", {"idem": id})
    return {"ok": True, "rejected": True}








































































































































































































































































































































































































































































































































































































































































