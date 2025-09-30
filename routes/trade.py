# routes/trade.py
from __future__ import annotations
import os, time, logging, inspect
from typing import Any, Dict, Optional, List, Callable

from fastapi import APIRouter, Header, HTTPException, Request, Body, Query
from pydantic import BaseModel, field_validator

logger = logging.getLogger("algogpt.trade")
router = APIRouter(tags=["trade"])

# --------- Metrics (optional, safe no-op) ----------
def _metrics_noop(*args, **kwargs):  # no-op if recorder missing
    return None

try:
    # צפה לממשק גנרי: record_counter(name, labels:dict, value:int) / record_gauge(name, value:float, labels:dict)
    from utils.metrics_recorder import record_counter, record_gauge  # type: ignore
except Exception:
    record_counter = _metrics_noop  # type: ignore
    record_gauge = _metrics_noop    # type: ignore

def _short_reason(s: str) -> str:
    s = (s or "").lower()
    if "4061" in s or "position side" in s: return "4061"
    if "bad_ticket_params" in s or "bad params" in s: return "bad_params"
    if "binance_keys_missing" in s: return "no_keys"
    if "binance_client_unavailable" in s: return "no_client"
    if "armed_execute_failed" in s: return "armed_failed"
    if "execute_trade_live_missing" in s: return "armed_missing"
    if "order_failed" in s: return "order_failed"
    if "open_ops_ticket_failed" in s: return "ticket_open_fail"
    return "other"

# --------- ConfirmStore (fallbacks) ----------
try:
    from utils.trade_executor import ConfirmStore  # type: ignore
except Exception:
    try:
        from utils.auto_executor import ConfirmStore  # type: ignore
    except Exception:
        # Fallback in-memory (main.py exposes a similar one)
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
def _is_code_4061(err: Exception | str) -> bool:
    s = str(err)
    return "code=-4061" in s or "position side does not match" in s.lower()

def _filter_kwargs_for_callable(fn: Callable[..., Any], kwargs: Dict[str, Any]) -> Dict[str, Any]:
    try:
        sig = inspect.signature(fn)
        allowed = set(sig.parameters.keys())
        return {k: v for k, v in kwargs.items() if k in allowed}
    except Exception:
        # ניקוי ידני של ארגומנטים בעייתיים בגרסאות שונות
        bad = {"tp_kind","sl_kind","entry_kind","entry_offset","tp_offset","sl_offset"}
        return {k: v for k, v in kwargs.items() if k not in bad}

async def _execute_trade_direct(ticket: Dict[str, Any]) -> Dict[str, Any]:
    """
    MARKET מיידי.
    קודם מנסה מתאם פנימי utils.trade_executor.place_futures_market;
    אם לא קיים/נכשל — Binance ישיר עם ריטריי חכם ל-4061.
    """
    # fast-path: אם יש מתאם פנימי אצלך
    try:
        from utils.trade_executor import place_futures_market  # type: ignore
        res = await place_futures_market(ticket)
        record_counter("trade_executed_total", {"flow":"MARKET","side":str(ticket.get("side","")).upper(),"outcome":"ok" if res.get("ok") else "fail"}, 1)
        if res.get("ok"):
            record_gauge("trade_last_exec_ts", float(time.time()), {"flow":"MARKET"})
        else:
            record_counter("trade_execute_fail_total", {"flow":"MARKET","side":str(ticket.get("side","")).upper(),"reason":_short_reason(str(res))}, 1)
        return res
    except Exception as e:
        # נמשיך ל-Binance ישיר
        pass

    if Client is None:
        record_counter("trade_execute_fail_total", {"flow":"MARKET","side":str(ticket.get("side","")).upper(),"reason":"no_client"}, 1)
        return {"ok": False, "error": "binance_client_unavailable"}

    try:
        api_key = os.getenv("BINANCE_API_KEY","").strip()
        api_sec = os.getenv("BINANCE_API_SECRET","").strip()
        if not (api_key and api_sec):
            record_counter("trade_execute_fail_total", {"flow":"MARKET","side":str(ticket.get("side","")).upper(),"reason":"no_keys"}, 1)
            return {"ok": False, "error": "binance_keys_missing"}
        client = Client(api_key, api_sec)

        symbol = str(ticket.get("symbol","")).upper()
        side = str(ticket.get("side","")).upper()
        qty = float(ticket.get("qty") or ticket.get("quantity") or 0)
        leverage = int(ticket.get("leverage") or 0)
        if not(symbol and side in ("BUY","SELL") and qty > 0 and leverage > 0):
            record_counter("trade_execute_fail_total", {"flow":"MARKET","side":side or "","reason":"bad_params"}, 1)
            return {"ok": False, "error": "bad_ticket_params"}

        # לא חובה שיצליח — לא מפיל הזמנה
        try:
            client.futures_change_leverage(symbol=symbol, leverage=leverage)
        except Exception as e:
            logger.warning("futures_change_leverage failed: %s", e)

        base_kwargs: Dict[str, Any] = {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quantity": qty,
            "newClientOrderId": f"{os.getenv('ORDER_ID_PREFIX','ALG_MAIN')}_{symbol}_{side}_{int(time.time())}",
        }

        pos_side_supplied = str(ticket.get("position_side") or ticket.get("positionSide") or "").upper()
        attempt_kwargs = dict(base_kwargs)
        if pos_side_supplied:
            attempt_kwargs["positionSide"] = pos_side_supplied

        try:
            order = client.futures_create_order(**attempt_kwargs)
            record_counter("trade_executed_total", {"flow":"MARKET","side":side,"outcome":"ok"}, 1)
            record_gauge("trade_last_exec_ts", float(time.time()), {"flow":"MARKET"})
            return {"ok": True, "exchange": "binance_futures", "order": order}
        except Exception as e1:
            if not _is_code_4061(e1):
                record_counter("trade_execute_fail_total", {"flow":"MARKET","side":side,"reason":_short_reason(str(e1))}, 1)
                return {"ok": False, "error": "order_failed", "detail": str(e1)}

            # ריטריי על 4061:
            try:
                if "positionSide" in attempt_kwargs:
                    retry_kwargs = dict(base_kwargs)  # הסרה
                else:
                    retry_kwargs = dict(base_kwargs)
                    retry_kwargs["positionSide"] = "LONG" if side == "BUY" else "SHORT"
                order = client.futures_create_order(**retry_kwargs)
                record_counter("trade_executed_total", {"flow":"MARKET","side":side,"outcome":"ok"}, 1)
                record_gauge("trade_last_exec_ts", float(time.time()), {"flow":"MARKET"})
                return {"ok": True, "exchange": "binance_futures", "order": order, "retry": True}
            except Exception as e2:
                record_counter("trade_execute_fail_total", {"flow":"MARKET","side":side,"reason":"4061"}, 1)
                return {"ok": False, "error": "order_failed", "detail": str(e2), "first_error": str(e1)}

    except Exception as e:
        record_counter("trade_execute_fail_total", {"flow":"MARKET","side":str(ticket.get("side","")).upper(),"reason":_short_reason(str(e))}, 1)
        return {"ok": False, "error": "order_failed", "detail": str(e)}

async def _execute_trade_hybrid(ticket: Dict[str, Any]) -> Dict[str, Any]:
    """
    HYBRID/AUTO – מפעיל execute_trade_live עם סינון דינמי של פרמטרים כדי למנוע TypeError.
    """
    try:
        try:
            from utils.trade_executor import execute_trade_live  # type: ignore
        except Exception:
            from app.trade_executor import execute_trade_live  # type: ignore
    except Exception as e:
        record_counter("trade_execute_fail_total", {"flow":"HYBRID","side":str(ticket.get("side","")).upper(),"reason":"armed_missing"}, 1)
        return {"ok": False, "error": "execute_trade_live_missing", "detail": str(e)}

    symbol = str(ticket.get("symbol","")).upper()
    side = str(ticket.get("side","")).upper()
    qty = float(ticket.get("qty") or ticket.get("quantity") or 0)
    leverage = int(ticket.get("leverage") or ticket.get("lev") or 0)
    pos_side = str(ticket.get("position_side") or ticket.get("positionSide") or ("LONG" if side=="BUY" else "SHORT")).upper()

    tps_raw = [ticket.get("tp1"), ticket.get("tp2"), ticket.get("tp3")]
    tp_targets = [float(x) for x in tps_raw if x not in (None, "0", "0.0") and float(x) > 0]
    sl_targets = [float(ticket.get("sl"))] if (ticket.get("sl") not in (None, 0, "0", "0.0")) else None

    if not (symbol and side in ("BUY","SELL") and qty > 0 and leverage > 0):
        record_counter("trade_execute_fail_total", {"flow":"HYBRID","side":side or "","reason":"bad_params"}, 1)
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
        record_counter("trade_executed_total", {"flow":"HYBRID","side":side,"outcome":"ok" if res.get("ok") else "fail"}, 1)
        if res.get("ok"):
            record_gauge("trade_last_exec_ts", float(time.time()), {"flow":"HYBRID"})
        else:
            record_counter("trade_execute_fail_total", {"flow":"HYBRID","side":side,"reason":_short_reason(str(res))}, 1)
        return res
    except Exception as e:
        record_counter("trade_execute_fail_total", {"flow":"HYBRID","side":side,"reason":"armed_failed"}, 1)
        return {"ok": False, "error": "armed_execute_failed", "detail": str(e)}

def _choose_flow(req: "TradeRequest") -> str:
    # אם יש TP/SL כנראה HYBRID, אחרת MARKET
    if any(x is not None for x in (req.tp1, req.tp2, req.tp3, req.sl)):
        return "HYBRID"
    return "MARKET"

# --------- Pydantic v2 models ----------
class TradeRequest(BaseModel):
    symbol: str
    side: str
    quantity: float
    leverage: int
    budget_usd: Optional[float] = None
    confirm_first: bool = False
    note: Optional[str] = None

    # אופציונליים:
    tp1: Optional[float] = None
    tp2: Optional[float] = None
    tp3: Optional[float] = None
    sl: Optional[float] = None
    tp_splits: Optional[List[float]] = None
    position_side: Optional[str] = None  # LONG/SHORT/BOTH
    reduce_only: Optional[bool] = False

    @field_validator("symbol")
    @classmethod
    def _sym_upper(cls, v: str) -> str:
        v = (v or "").strip().upper()
        if not v:
            raise ValueError("symbol required")
        return v

    @field_validator("side")
    @classmethod
    def _side_upper(cls, v: str) -> str:
        v = (v or "").strip().upper()
        if v not in ("BUY", "SELL"):
            raise ValueError("side must be BUY/SELL")
        return v

    @field_validator("quantity")
    @classmethod
    def _qty_pos(cls, v: float) -> float:
        if v is None or float(v) <= 0:
            raise ValueError("quantity must be > 0")
        return float(v)

    @field_validator("leverage")
    @classmethod
    def _lev_pos(cls, v: int) -> int:
        iv = int(v or 0)
        if iv <= 0:
            raise ValueError("leverage must be > 0")
        return iv

# --------- API ---------

@router.post("/trade/execute")
async def trade_execute(
    req: TradeRequest = Body(...),
    request: Request = None,
    x_idempotency_key: Optional[str] = Header(default=None, alias="X-Idempotency-Key"),
):
    """
    אם confirm_first=true או REQUIRE_TELEGRAM_APPROVAL=1 – נפתח טיקט דרך /ops/ticket (שולח טלגרם),
    ומחזירים pending_approval עם קישורי Approve/Reject/Preview.
    אחרת – ביצוע מיידי:
      * MARKET ללא TP/SL דרך Binance (עם ריטריי 4061)
      * HYBRID עם TP/SL דרך execute_trade_live (סינון דינמי)
    """
    force_approve = os.getenv("REQUIRE_TELEGRAM_APPROVAL","0").lower() in ("1","true","yes","on")
    need_approval = bool(req.confirm_first or force_approve)

    # רישום בקשה
    flow = _choose_flow(req)
    record_counter("trade_requests_total", {"flow":flow, "side":req.side, "source":"approval" if need_approval else "api"}, 1)

    # אישור-טלגרם: פותחים טיקט דרך /ops/ticket (שולח הודעה עם כפתורים)
    if need_approval:
        try:
            import httpx
            public_host = os.getenv("PUBLIC_HOST","").strip()
            base = public_host if public_host else (str(request.base_url).rstrip("/") if request else "http://127.0.0.1:10000")
            payload = {
                "symbol": req.symbol,
                "side": req.side,
                "qty": req.quantity,
                "leverage": req.leverage,
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
            if api_key:
                headers["X-API-Key"] = api_key.strip()
            async with httpx.AsyncClient(timeout=12.0) as cli:
                r = await cli.post(f"{base.rstrip('/')}/ops/ticket", json=payload, headers=headers)
            data = r.json()
            if not data.get("ok"):
                raise RuntimeError(f"ops.ticket failed: {data}")
            record_counter("trade_approvals_total", {"flow":flow,"side":req.side}, 1)
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
            record_counter("trade_execute_fail_total", {"flow":flow,"side":req.side,"reason":"ticket_open_fail"}, 1)
            raise HTTPException(status_code=502, detail=f"open_ops_ticket_failed: {e}")

    # ביצוע מיידי
    ticket_exec = dict(
        symbol=req.symbol,
        side=req.side,
        qty=req.quantity,
        leverage=req.leverage,
        note=req.note or "",
        tp1=req.tp1, tp2=req.tp2, tp3=req.tp3, sl=req.sl,
        tp_splits=req.tp_splits,
        position_side=(req.position_side or ("LONG" if req.side=="BUY" else "SHORT")).upper(),
        reduce_only=bool(req.reduce_only),
    )

    if flow == "MARKET":
        res = await _execute_trade_direct(ticket_exec)
    else:
        res = await _execute_trade_hybrid(ticket_exec)

    record_counter("trade_executed_total", {"flow":flow,"side":req.side,"outcome":"ok" if res.get("ok") else "fail"}, 1)
    if res.get("ok"):
        record_gauge("trade_last_exec_ts", float(time.time()), {"flow":flow})
    else:
        record_counter("trade_execute_fail_total", {"flow":flow,"side":req.side,"reason":_short_reason(str(res))}, 1)

    return {"ok": bool(res.get("ok")), "flow": flow, "result": res}

@router.get("/trade/approve")
async def trade_approve(id: str = Query(..., description="idempotency key or ticket_id")):
    # חיפוש טיקט ב-ConfirmStore (תמיכה לאחור)
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
        return {"ok": False, "error": "not_found"}

    flow = "HYBRID" if any(it.get(k) for k in ("tp1","tp2","tp3","sl")) else "MARKET"
    res = await (_execute_trade_hybrid(it) if flow=="HYBRID" else _execute_trade_direct(it))
    ok = bool(res.get("ok"))

    try:
        ConfirmStore.decide(str(it.get("ticket_id") or id), approved=ok)
    except Exception:
        pass

    record_counter("trade_executed_total", {"flow":flow,"side":str(it.get("side","")).upper(),"outcome":"ok" if ok else "fail"}, 1)
    if ok:
        record_gauge("trade_last_exec_ts", float(time.time()), {"flow":flow})
    else:
        record_counter("trade_execute_fail_total", {"flow":flow,"side":str(it.get("side","")).upper(),"reason":_short_reason(str(res))}, 1)

    return {"ok": ok, "flow": flow, "result": res}

@router.get("/trade/reject")
async def trade_reject(id: str = Query(..., description="idempotency key or ticket_id")):
    try:
        ConfirmStore.decide(str(id), approved=False)
    except Exception:
        pass
    record_counter("trade_rejections_total", {"flow":"unknown","side":"unknown"}, 1)
    return {"ok": True, "rejected": True, "id": id}




















































































































































































































































































































































































































































































































































































































































































