# routes/trade.py
from __future__ import annotations
import os, time, logging, inspect
from typing import Any, Dict, Optional, List, Callable

from fastapi import APIRouter, Header, HTTPException, Request, Body, Query
from pydantic import BaseModel, field_validator

logger = logging.getLogger("algogpt.trade")
router = APIRouter(tags=["trade"])

# ---------- metrics wiring (optional) ----------
try:
    from routes.metrics import (
        record_trade_request, record_trade_ok, record_trade_fail, record_trade_approval
    )
except Exception:
    def record_trade_request(flow: Optional[str] = None): pass
    def record_trade_ok(flow: Optional[str] = None): pass
    def record_trade_fail(flow: Optional[str] = None): pass
    def record_trade_approval(action: str, ok: bool): pass

# --------- ConfirmStore (fallbacks) ----------
try:
    from utils.trade_executor import ConfirmStore  # type: ignore
except Exception:
    try:
        from utils.auto_executor import ConfirmStore  # type: ignore
    except Exception:
        class ConfirmStore:  # type: ignore
            _P: Dict[str, Dict[str, Any]] = {}
            @classmethod
            def pending(cls) -> List[Dict[str, Any]]:
                return list(cls._P.values())
            @classmethod
            def create(cls, payload: Dict[str, Any]) -> str:
                tid = payload.get("ticket_id") or f"TKT-{int(time.time()*1000)}"
                payload["ticket_id"] = tid
                payload.setdefault("created_ts", int(time.time()))
                payload.setdefault("ttl_sec", int(os.getenv("OPS_TICKET_TTL_SEC", "1800")))
                cls._P[tid] = payload
                return tid
            @classmethod
            def get(cls, ticket_id: str) -> Optional[Dict[str, Any]]:
                return cls._P.get(ticket_id)
            @classmethod
            def decide(cls, ticket_id: str, approved: bool) -> Dict[str, Any]:
                it = cls._P.pop(ticket_id, None)
                if not it:
                    return {"ok": False, "error": "not_found"}
                it["approved"] = approved
                it["decided_ts"] = int(time.time())
                return {"ok": True, "approved": approved, "ticket_id": ticket_id}

# --------- Binance client optional ----------
try:
    from binance.client import Client  # type: ignore
except Exception:
    Client = None  # type: ignore

# --------- helpers ----------
def _hedge_mode_enabled() -> bool:
    if os.getenv("POSITION_MODE_OVERRIDE","").strip().lower() in ("hedge","hedged"):
        return True
    if os.getenv("BINANCE_FORCE_HEDGE_MODE","").strip().lower() in ("1","true","yes","on"):
        return True
    return False

def _is_code_4061(err: Exception | str) -> bool:
    s = str(err)
    return "code=-4061" in s or "position side does not match" in s.lower()

def _filter_kwargs_for_callable(fn: Callable[..., Any], kwargs: Dict[str, Any]) -> Dict[str, Any]:
    try:
        sig = inspect.signature(fn)
        allowed = set(sig.parameters.keys())
        return {k: v for k, v in kwargs.items() if k in allowed}
    except Exception:
        bad = {"tp_kind","sl_kind","entry_kind","entry_offset","tp_offset","sl_offset"}
        return {k: v for k, v in kwargs.items() if k not in bad}

async def _execute_trade_direct(ticket: Dict[str, Any]) -> Dict[str, Any]:
    # fast-path דרך מתאם פנימי אם זמין
    try:
        from utils.trade_executor import place_futures_market  # type: ignore
        return await place_futures_market(ticket)
    except Exception:
        pass

    if Client is None:
        return {"ok": False, "error": "binance_client_unavailable"}

    try:
        api_key = os.getenv("BINANCE_API_KEY","").strip()
        api_sec = os.getenv("BINANCE_API_SECRET","").strip()
        if not (api_key and api_sec):
            return {"ok": False, "error": "binance_keys_missing"}
        client = Client(api_key, api_sec)

        symbol = str(ticket.get("symbol","")).upper()
        side = str(ticket.get("side","")).upper()
        qty = float(ticket.get("qty") or ticket.get("quantity") or 0)
        leverage = int(ticket.get("leverage") or 0)
        if not(symbol and side in ("BUY","SELL") and qty > 0 and leverage > 0):
            return {"ok": False, "error": "bad_ticket_params"}

        try:
            client.futures_change_leverage(symbol=symbol, leverage=leverage)
        except Exception as e:
            logger.warning("futures_change_leverage failed: %s", e)

        base_kwargs: Dict[str, Any] = {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quantity": qty,
            "newClientOrderId": f"{os.getenv('ORDER_ID_PREFIX','ALG')}_{symbol}_{side}_{int(time.time())}",
        }

        pos_side_supplied = str(ticket.get("position_side") or ticket.get("positionSide") or "").upper()
        attempt_order = dict(base_kwargs)
        if pos_side_supplied:
            attempt_order["positionSide"] = pos_side_supplied
        elif _hedge_mode_enabled():
            attempt_order["positionSide"] = "LONG" if side == "BUY" else "SHORT"

        try:
            order = client.futures_create_order(**attempt_order)
            return {"ok": True, "exchange": "binance_futures", "order": order}
        except Exception as e1:
            if not _is_code_4061(e1):
                logger.error("futures_create_order failed: %s", e1)
                return {"ok": False, "error": "order_failed", "detail": str(e1)}
            # ‎-4061: נסה בלי/עם הצד ההפוך
            try:
                if "positionSide" in attempt_order:
                    retry_kwargs = dict(base_kwargs)
                else:
                    retry_kwargs = dict(base_kwargs)
                    retry_kwargs["positionSide"] = "LONG" if side == "BUY" else "SHORT"
                order = client.futures_create_order(**retry_kwargs)
                return {"ok": True, "exchange": "binance_futures", "order": order, "retry": True}
            except Exception as e2:
                logger.error("futures_create_order after 4061 retry failed: %s", e2)
                return {"ok": False, "error": "order_failed", "detail": str(e2), "first_error": str(e1)}
    except Exception as e:
        logger.error("order_execute_direct_failed: %s", e)
        return {"ok": False, "error": "order_failed", "detail": str(e)}

async def _execute_trade_hybrid(ticket: Dict[str, Any]) -> Dict[str, Any]:
    try:
        try:
            from utils.trade_executor import execute_trade_live  # type: ignore
        except Exception:
            from app.trade_executor import execute_trade_live  # type: ignore
    except Exception as e:
        return {"ok": False, "error": "execute_trade_live_missing", "detail": str(e)}

    symbol = str(ticket.get("symbol","")).upper()
    side = str(ticket.get("side","")).upper()
    qty = float(ticket.get("qty") or ticket.get("quantity") or 0)
    leverage = int(ticket.get("leverage") or ticket.get("lev") or 0)
    pos_side = str(ticket.get("position_side") or ticket.get("positionSide") or ("LONG" if side=="BUY" else "SHORT")).upper()

    tps_raw = [ticket.get("tp1"), ticket.get("tp2"), ticket.get("tp3")]
    tp_targets = [float(x) for x in tps_raw if x is not None and str(x) not in ("0","0.0") and float(x) > 0]
    sl_targets = [float(ticket.get("sl"))] if (ticket.get("sl") not in (None, 0, "0", "0.0")) else None

    if not (symbol and side in ("BUY","SELL") and qty > 0 and leverage > 0):
        return {"ok": False, "error": "bad_ticket_params"}

    base_kwargs: Dict[str, Any] = dict(
        symbol=symbol,
        side=side,
        budget=None,
        leverage=leverage,
        dry_run=False,
        quantity=qty,
        entry=None,
        tp_targets=tp_targets or None,
        sl_targets=sl_targets or None,
        tp_splits=ticket.get("tp_splits"),
        sl_splits=None,
        confirm_first=False,
        telegram_chat_id=int(os.getenv("TELEGRAM_CHAT_ID") or 0),
        position_side=pos_side,
        reduce_only=bool(ticket.get("reduce_only", False)),
    )
    clean = _filter_kwargs_for_callable(execute_trade_live, base_kwargs)

    try:
        res = await execute_trade_live(**clean)
        return res
    except Exception as e:
        return {"ok": False, "error": "armed_execute_failed", "detail": str(e)}

def _choose_flow(req: "TradeRequest") -> str:
    if any(x is not None for x in (req.tp1, req.tp2, req.tp3, req.sl)):
        return "HYBRID"
    return "MARKET"

class TradeRequest(BaseModel):
    symbol: str
    side: str
    quantity: float
    leverage: int
    budget_usd: Optional[float] = None
    confirm_first: bool = False
    note: Optional[str] = None
    tp1: Optional[float] = None
    tp2: Optional[float] = None
    tp3: Optional[float] = None
    sl: Optional[float] = None
    tp_splits: Optional[List[float]] = None
    position_side: Optional[str] = None
    reduce_only: Optional[bool] = False

    @field_validator("symbol")
    @classmethod
    def _sym_upper(cls, v: str) -> str:
        v = (v or "").strip().upper()
        if not v: raise ValueError("symbol required")
        return v

    @field_validator("side")
    @classmethod
    def _side_upper(cls, v: str) -> str:
        v = (v or "").strip().upper()
        if v not in ("BUY", "SELL"): raise ValueError("side must be BUY/SELL")
        return v

    @field_validator("quantity")
    @classmethod
    def _qty_pos(cls, v: float) -> float:
        if v is None or float(v) <= 0: raise ValueError("quantity must be > 0")
        return float(v)

    @field_validator("leverage")
    @classmethod
    def _lev_pos(cls, v: int) -> int:
        iv = int(v or 0)
        if iv <= 0: raise ValueError("leverage must be > 0")
        return iv

@router.post("/trade/execute")
async def trade_execute(
    req: TradeRequest = Body(...),
    request: Request,  # ← תיקון: לא Optional, בלי ברירת מחדל
    x_idempotency_key: Optional[str] = Header(default=None, alias="X-Idempotency-Key"),
):
    flow = _choose_flow(req)
    record_trade_request(flow)

    force_approve = os.getenv("REQUIRE_TELEGRAM_APPROVAL","0").lower() in ("1","true","yes","on")
    need_approval = bool(req.confirm_first or force_approve)

    if need_approval:
        try:
            import httpx
            public_host = os.getenv("PUBLIC_HOST","").strip()
            base = public_host if public_host else (str(request.base_url).rstrip("/") if request else "http://127.0.0.1:10000")
            payload = {
                "symbol": req.symbol, "side": req.side, "qty": req.quantity, "leverage": req.leverage,
                "tp1": req.tp1, "tp2": req.tp2, "tp3": req.tp3, "sl": req.sl,
                "tp_splits": req.tp_splits,
                "position_side": (req.position_side or ("LONG" if req.side=="BUY" else "SHORT")).upper(),
                "note": req.note or "",
            }
            headers: Dict[str,str] = {}
            api_key = (
                os.getenv("API_TOKEN")
                or os.getenv("PRIMARY_API_TOKEN")
                or os.getenv("API_BEARER_TOKEN")
                or os.getenv("ALGOGPT_API_TOKEN")
            )
            if api_key: headers["X-API-Key"] = api_key.strip()
            async with httpx.AsyncClient(timeout=12.0) as cli:
                r = await cli.post(f"{base.rstrip('/')}/ops/ticket", json=payload, headers=headers)
            data = r.json()
            if not data.get("ok"): raise RuntimeError(f"ops.ticket failed: {data}")
            return {
                "ok": False,
                "error": "pending_approval",
                "result": {
                    "reason": "pending",
                    "ticket_id": data.get("ticket_id"),
                    "approve_url": data.get("approve_url"),
                    "reject_url": data.get("reject_url"),
                    "preview_url": data.get("preview_url"),
                    "ttl_sec": int(os.getenv("OPS_TICKET_TTL_SEC","1800")),
                },
            }
        except Exception as e:
            logger.error("open_ops_ticket_failed: %s", e)
            record_trade_fail(flow)
            raise HTTPException(status_code=502, detail=f"open_ops_ticket_failed: {e}")

    ticket_exec = dict(
        symbol=req.symbol, side=req.side, qty=req.quantity, leverage=req.leverage,
        note=req.note or "", tp1=req.tp1, tp2=req.tp2, tp3=req.tp3, sl=req.sl,
        tp_splits=req.tp_splits, position_side=(req.position_side or ("LONG" if req.side=="BUY" else "SHORT")).upper(),
        reduce_only=bool(req.reduce_only),
    )

    res = await (_execute_trade_direct(ticket_exec) if flow=="MARKET" else _execute_trade_hybrid(ticket_exec))
    ok = bool(res.get("ok"))
    (record_trade_ok if ok else record_trade_fail)(flow)
    return {"ok": ok, "flow": flow, "result": res}

@router.get("/trade/approve")
async def trade_approve(id: str = Query(..., description="idempotency key or ticket_id")):
    it: Optional[Dict[str, Any]] = None
    try:
        for t in (ConfirmStore.pending() or []):
            if str(t.get("idem") or t.get("ticket_id")) == str(id):
                it = t; break
    except Exception:
        try:
            it = ConfirmStore.get(id)  # type: ignore
        except Exception:
            it = None

    if not it:
        record_trade_approval("approve", False)
        return {"ok": False, "error": "not_found"}

    flow = "HYBRID" if any(it.get(k) for k in ("tp1","tp2","tp3","sl")) else "MARKET"
    res = await (_execute_trade_hybrid(it) if flow=="HYBRID" else _execute_trade_direct(it))
    ok = bool(res.get("ok"))

    try:
        ConfirmStore.decide(str(it.get("ticket_id") or id), approved=ok)
    except Exception:
        pass

    record_trade_approval("approve", ok)
    (record_trade_ok if ok else record_trade_fail)(flow)

    return {"ok": ok, "flow": flow, "result": res}

@router.get("/trade/reject")
async def trade_reject(id: str = Query(..., description="idempotency key or ticket_id")):
    try:
        ConfirmStore.decide(str(id), approved=False)
        ok = True
    except Exception:
        ok = False
    record_trade_approval("reject", ok)
    record_trade_fail("HYBRID")
    return {"ok": True, "rejected": True, "id": id}























































































































































































































































































































































































































































































































































































































































































