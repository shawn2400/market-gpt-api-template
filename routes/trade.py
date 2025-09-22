# routes/trade.py
from __future__ import annotations
import time, secrets
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
import httpx

from utils.auth import require_api_key

# === Telegram notifiers (best-effort) ===
try:
    from utils.telegram_notifier import send_trade_approval as send_approval  # type: ignore
    from utils.telegram_notifier import notify_ops_alert as send_audit        # type: ignore
except Exception:
    async def send_approval(*args, **kwargs):  # type: ignore
        return None
    async def send_audit(*args, **kwargs):     # type: ignore
        return None

# === Auto-approve rules (אם קיימות) ===
try:
    from utils.approval_rules import should_auto_approve  # type: ignore
except Exception:
    def should_auto_approve(payload: Dict[str, Any]):  # type: ignore
        return (False, "rules_missing")

# === Trade executor (חי) ===
try:
    from utils.trade_executor import execute_trade_live  # type: ignore
except Exception:
    execute_trade_live = None  # type: ignore

router = APIRouter(tags=["trade"])

# זיכרון בקשות בהמתנה לאישור ידני
_PENDING: Dict[str, Dict[str, Any]] = {}
_PENDING_TTL = 60 * 5  # 5 דקות

def _make_idem(x: Optional[str]) -> str:
    return x or f"{int(time.time()*1000)}_{secrets.token_hex(6)}"

class TradeReq(BaseModel):
    symbol: str
    side: str
    quantity: float = Field(gt=0)
    leverage: int = Field(ge=1, le=125)
    budget_usd: float = Field(gt=0)  # נשמר ב-API (לוג/אישור) — לא נשלח ל-executor
    position_side: Optional[str] = "BOTH"
    note: Optional[str] = None
    dry_run: bool = False
    confirm_first: bool = False
    tp_targets: Optional[List[float]] = None
    tp_splits: Optional[List[float]] = None

    @field_validator("side")
    @classmethod
    def _side_ok(cls, v: str) -> str:
        vu = v.upper()
        if vu not in ("BUY", "SELL", "LONG", "SHORT"):
            raise ValueError("side must be BUY/SELL/LONG/SHORT")
        return "BUY" if vu in ("BUY", "LONG") else "SELL"

    @field_validator("position_side")
    @classmethod
    def _ps_ok(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return "BOTH"
        vu = v.upper()
        if vu not in ("BOTH", "LONG", "SHORT"):
            raise ValueError("position_side must be BOTH/LONG/SHORT")
        return vu

    @field_validator("tp_splits")
    @classmethod
    def _splits_sum_ok(cls, v: Optional[List[float]]):
        if v is not None and sum(v) > 1.0 + 1e-9:
            raise ValueError("sum(tp_splits) must be <= 1")
        return v

def _422(detail: Any) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail)

def _summary(req: TradeReq) -> str:
    return f"{req.side.upper()} {req.symbol.upper()} qty={req.quantity} lev={req.leverage} budget=${req.budget_usd} dry={req.dry_run}"

async def _execute_and_audit(req: TradeReq) -> Dict[str, Any]:
    """
    קריאה נקייה ל-execute_trade_live ללא פרמטרים שלא נתמכים.
    **לא מעבירים budget בכלל** — משתמשים ב-quantity שכבר התקבל ב-API.
    """
    if execute_trade_live is None:
        raise RuntimeError("trade executor missing")

    res = await execute_trade_live(
        symbol=req.symbol,
        side=req.side,
        quantity=req.quantity,
        leverage=req.leverage,
        position_side=req.position_side or "BOTH",
        note=req.note or "trade_execute_api",
    )
    try:
        await send_audit(f"TRADE EXECUTE API · {_summary(req)}")
    except Exception:
        pass
    return res

@router.post("/trade/execute")
async def trade_execute(
    req: TradeReq,
    request: Request,
    _token: str = Depends(require_api_key),
    x_idem: Optional[str] = Header(default=None, alias="X-Idempotency-Key"),
) -> Dict[str, Any]:
    idem = _make_idem(x_idem)
    auto, reason = should_auto_approve(req.model_dump())
    need_approval = bool(req.confirm_first and not req.dry_run and not auto)

    if need_approval:
        # נשמור בקשה + TTL
        _PENDING[idem] = {"ts": time.time(), "req": req.model_dump()}
        # plan מינימלי להודעת אישור
        plan = {
            "symbol": req.symbol,
            "side": req.side,
            "leverage": req.leverage,
            "quantity": req.quantity,
            "budget_usd": req.budget_usd,
            "tp": [{"stopPrice": t} for t in (req.tp_targets or [])],
            "ttl_sec": _PENDING_TTL,
            "trade_kind": "Futures",
            "order_type": "MARKET",  # שמרנו פשטות – ללא limit/entry
            "why": "trade_execute_api_confirm_first",
        }
        try:
            await send_approval(idem, plan)  # inline keyboard / links
        except Exception:
            pass
        return {"ok": False, "error": "pending_approval", "result": {"reason": "pending", "idem": idem, "ttl_sec": _PENDING_TTL}}

    try:
        res = await _execute_and_audit(req)
        if auto and not req.dry_run:
            try:
                await send_audit(f"AUTO-APPROVED · idem={idem} · reason={reason}")
            except Exception:
                pass
        return {"ok": True, "error": None, "result": res}
    except ValueError as ve:
        raise _422([{"type":"value_error","loc":["body"],"msg":str(ve)}])
    except httpx.HTTPStatusError as he:
        raise HTTPException(status_code=502, detail={"error": "binance_http", "status": he.response.status_code, "body": he.response.text})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# נקודות קצה ציבוריות (לינקים בהודעות טלגרם)
@router.get("/trade/approve", include_in_schema=False)
async def trade_approve(id: str) -> Dict[str, Any]:
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
async def trade_reject(id: str) -> Dict[str, Any]:
    _PENDING.pop(id, None)
    try:
        await send_audit(f"REJECTED · idem={id}")
    except Exception:
        pass
    return {"ok": True, "rejected": True}

# תאימות לאחראי־אישורים הישן (ops_approval)
TradeRequest = TradeReq  # alias
def execute_real_trade(req: TradeRequest, preview: Dict[str, Any] | None = None) -> Dict[str, Any]:
    import anyio
    return anyio.from_thread.run(_execute_and_audit, req)  # type: ignore








































































































































































































































































































































































































































































































































































































































































