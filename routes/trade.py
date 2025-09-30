# routes/trade.py
from __future__ import annotations
import os, time, secrets
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator, ValidationInfo
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

# === Approvals unified store & sender ===
from utils.approvals import ConfirmStore, send_confirm_request  # type: ignore

router = APIRouter(tags=["trade"])

_PENDING: Dict[str, Dict[str, Any]] = {}
_PENDING_TTL = 60 * 5  # 5 דקות

def _make_idem(x: Optional[str]) -> str:
    return x or f"{int(time.time()*1000)}_{secrets.token_hex(6)}"

class TradeReq(BaseModel):
    symbol: str
    side: str
    quantity: float = Field(gt=0)
    leverage: int = Field(ge=1, le=125)
    budget_usd: float = Field(gt=0)
    position_side: Optional[str] = "BOTH"
    note: Optional[str] = None
    dry_run: bool = False
    confirm_first: bool = False

    tp: Optional[float] = None
    sl: Optional[float] = None
    tp_targets: Optional[List[float]] = None
    tp_splits: Optional[List[float]] = None
    sl_targets: Optional[List[float]] = None
    sl_splits: Optional[List[float]] = None

    @field_validator("side")
    @classmethod
    def _side_ok(cls, v: str) -> str:
        vu = v.upper()
        if vu not in ("BUY","SELL","LONG","SHORT"):
            raise ValueError("side must be BUY/SELL/LONG/SHORT")
        return "BUY" if vu in ("BUY","LONG") else "SELL"

    @field_validator("position_side")
    @classmethod
    def _ps_ok(cls, v: Optional[str], info: ValidationInfo) -> Optional[str]:
        side = (info.data.get("side") or "").upper()
        hedge = os.getenv("BINANCE_FORCE_HEDGE_MODE", "true").lower() in ("1", "true", "yes", "on")

        if v is None:
            return "LONG" if (hedge and side == "BUY") else ("SHORT" if (hedge and side == "SELL") else "BOTH")

        v2 = v.upper()
        if v2 not in ("BOTH", "LONG", "SHORT"):
            raise ValueError("position_side must be BOTH/LONG/SHORT")

        if hedge and v2 == "BOTH":
            return "LONG" if side == "BUY" else "SHORT"
        return v2

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

# --- lazy import of executor (מונע כשלים בזמן טעינת ראוטים) ---
def _get_executor():
    try:
        from utils.trade_executor import execute_trade_live  # type: ignore
        return execute_trade_live
    except Exception:
        return None

async def _execute_and_audit(req: TradeReq) -> Dict[str, Any]:
    execute_trade_live = _get_executor()
    if execute_trade_live is None:
        raise RuntimeError("trade executor missing")

    res = await execute_trade_live(
        symbol=req.symbol,
        side=req.side,
        budget=req.budget_usd,
        leverage=req.leverage,
        dry_run=req.dry_run,
        quantity=req.quantity,
        position_side=req.position_side or "BOTH",
        confirm_first=req.confirm_first,
        tp=req.tp,
        sl=req.sl,
        tp_targets=req.tp_targets,
        tp_splits=req.tp_splits,
        sl_targets=req.sl_targets,
        sl_splits=req.sl_splits,
    )
    try:
        extra = f" · note={req.note}" if req.note else ""
        await send_audit(f"TRADE EXECUTE API · {_summary(req)}{extra}")
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

    try:
        auto, reason = should_auto_approve({"budget_usd": req.budget_usd})
    except Exception:
        auto, reason = (False, "rules_missing")

    need_approval = bool(req.confirm_first and not req.dry_run and not auto)

    if need_approval:
        _PENDING[idem] = {"ts": time.time(), "req": req.model_dump()}

        plan = {
            "symbol": req.symbol,
            "side": req.side,
            "leverage": req.leverage,
            "quantity": req.quantity,
            "budget_usd": req.budget_usd,
            "tp": [{"stopPrice": t} for t in (req.tp_targets or [])],
            "ttl_sec": _PENDING_TTL,
            "trade_kind": "Futures",
            "order_type": "MARKET",
            "why": "trade_execute_api_confirm_first",
        }

        # להצמיד handler לאישור
        def _runner():
            import anyio
            return anyio.from_thread.run(_execute_and_audit, req)

        try:
            ConfirmStore.create_with_id(idem, plan)
            ConfirmStore.set_handler(idem, _runner)
        except Exception:
            pass

        sent = False
        try:
            await send_confirm_request(idem, plan); sent = True
        except Exception:
            sent = False
        if not sent:
            try:
                await send_approval(idem, plan)  # fallback
            except Exception:
                pass

        return {"ok": False, "error": "pending_approval", "result": {"reason": "pending", "idem": idem, "ttl_sec": _PENDING_TTL}}

    # ללא אישור – ריצה מידית
    try:
        res = await _execute_and_audit(req)
        if auto and not req.dry_run:
            try:
                await send_audit(f"AUTO-APPROVED · idem={idem} · reason={reason}")
            except Exception:
                pass
        return {"ok": True, "error": None, "result": res}
    except ValueError as ve:
        raise _422([{"type": "value_error", "loc": ["body"], "msg": str(ve)}])
    except httpx.HTTPStatusError as he:
        raise HTTPException(status_code=502, detail={"error": "binance_http", "status": he.response.status_code, "body": he.response.text})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/trade/approve", include_in_schema=False)
async def trade_approve(id: str) -> Dict[str, Any]:
    # ניסיון דרך ConfirmStore
    try:
        if ConfirmStore.has(id):
            _ = ConfirmStore.decide(id, approved=True)
            started = await ConfirmStore.run(id)
            return {"ok": True, "result": {"confirm": _, "run": started}}
    except Exception:
        pass

    # תאימות לאחור
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
    try:
        if ConfirmStore.has(id):
            _ = ConfirmStore.decide(id, approved=False)
            try:
                await send_audit(f"REJECTED · idem={id}")
            except Exception:
                pass
            return {"ok": True, "rejected": True, "result": _}
    except Exception:
        pass

    _PENDING.pop(id, None)
    try:
        await send_audit(f"REJECTED · idem={id}")
    except Exception:
        pass
    return {"ok": True, "rejected": True}


















































































































































































































































































































































































































































































































































































































































































