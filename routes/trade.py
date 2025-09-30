# routes/trade.py
from __future__ import annotations
import os, time, logging, inspect
from typing import Any, Dict, Optional, List, Callable

from fastapi import APIRouter, Header, HTTPException, Request, Body, Query
from pydantic import BaseModel, field_validator

logger = logging.getLogger("algogpt.trade")
router = APIRouter(tags=["trade"])

# --- (optional) metrics wiring ---
try:
    from routes.metrics import (
        record_trade_requested,
        record_trade_approved,
        record_trade_rejected,
        record_trade_executed,
    )
except Exception:
    def record_trade_requested(*args, **kwargs): pass
    def record_trade_approved(*args, **kwargs): pass
    def record_trade_rejected(*args, **kwargs): pass
    def record_trade_executed(*args, **kwargs): pass

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
def _hedge_mode_enabled() -> bool:
    if os.getenv("POSITION_MODE_OVERRIDE","").strip().lower() in ("hedge","hedged"):
        return True
    if os.getenv("BINANCE_FORCE_HEDGE_MODE","").strip().lower() in ("1","true","yes","on"):
        return True
    return False

def _filter_kwargs_for_callable(fn: Callable[..., Any], kwargs: Dict[str, Any]) -> Dict[str, Any]:
    try:
        sig = inspect.signature(fn)
        allowed = set(sig.parameters.keys())
        return {k: v for k, v in kwargs.items() if k in allowed}
    except Exception:
        # ניקוי ידני של ארגומנטים בעייתיים בגרסאות שונות
        bad = {"tp_kind","sl_kind","entry_kind","entry_offset","tp_offset","sl_offset"}
        return {k: v for k, v in kwargs.items() if k not in bad}

def _is_code_4061(err: Exception | str) -> bool:
    s = str(err)
    return "code=-4061" in s or "position side does not match" in s.lower()

async def _execute_trade_direct(ticket: Dict[str, Any]) -> Dict[str, Any]:
    """
    MARKET מיידי דרך utils.trade_executor.place_futures_market אם קיים;
    אחרת באמצעות binance-python, עם מנגנון ריטריי חכם ל-4061 (עם/בלי positionSide).
    """
    # fast-path: אם יש מתאם פנימי אצלך
    try:
        from utils.trade_executor import place_futures_market  # type: ignore
        res = await place_futures_market(ticket)
        return res
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
            "newClientOrderId": f"{os.getenv('ORDER_ID_PREFIX','ALG')}_{symbol}_{side}_{int(time.time())}",
        }

        # ניסיון 1: אם המשתמש סיפק position_side — נשתמש בו; אחרת — ללא שדה
        supplied_pos = str(ticket.get("position_side") or ticket.get("positionSide") or "").upper()
        attempt1 = dict(base_kwargs)
        if supplied_pos:
            attempt1["positionSide"] = supplied_pos

        try:
            order = client.futures_create_order(**attempt1)
            return {"ok": True, "exchange": "binance_futures", "order": order}
        except Exception as e1:
            if not _is_code_4061(e1):
                raise

            # ניסיון 2: היפוך לוגיקה — אם היה positionSide נסיר; אם לא היה — נוסיף LONG/SHORT מפורש
            try:
                if "positionSide" in attempt1:
                    attempt2 = dict(base_kwargs)
                else:
                    attempt2 = dict(base_kwargs)
                    attempt2["positionSide"] = "LONG" if side == "BUY" else "SHORT"
                order = client.futures_create_order(**attempt2)
                return {"ok": True, "exchange": "binance_futures", "order": order, "retry": True}
            except Exception as e2:
                logger.error("futures_create_order after 4061 retry failed: %s", e2)
                return {"ok": False, "error": "order_failed", "detail": str(e2), "first_error": str(e1)}
    except Exception as e:
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
      * MARKET ללא TP/SL דרך Binance (עם ריטריי -4061)
      * HYBRID עם TP/SL דרך execute_trade_live (סינון דינמי)
    """
    # metrics: trade requested
    try:
        record_trade_requested(symbol=req.symbol, side=req.side, mode="confirm" if req.confirm_first else "direct")
    except Exception:
        pass

    force_approve = os.getenv("REQUIRE_TELEGRAM_APPROVAL","0").lower() in ("1","true","yes","on")
    need_approval = bool(req.confirm_first or force_approve)

    # אישור-טלגרם: פותחים טיקט דרך /ops/ticket (שולח הודעה עם כפתורים)
    if need_approval:
        try:
            import httpx
            public_host = os.getenv("PUBLIC_HOST","").strip()
            # בסיס לכתובת: PUBLIC_HOST אם הוגדר, אחרת מהבקשה
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
            try:
                data = r.json()
            except Exception:
                raise RuntimeError(f"/ops/ticket bad response: {r.status_code} {r.text[:200]}")
            if not data.get("ok"):
                raise RuntimeError(f"ops.ticket failed: {data}")

            try:
                record_trade_requested(symbol=req.symbol, side=req.side, mode="pending_approval")
            except Exception:
                pass

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
            raise HTTPException(status_code=502, detail=f"open_ops_ticket_failed: {e}")

    # ביצוע מיידי
    flow = _choose_flow(req)
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

    ok = bool(res.get("ok"))
    try:
        if ok:
            record_trade_executed(symbol=req.symbol, side=req.side, flow=flow, via="direct")
        else:
            # לא מסמנים rejected כאן — זה כשל ביצוע, לא דחייה אקטיבית
            pass
    except Exception:
        pass

    return {"ok": ok, "flow": flow, "result": res}

@router.get("/trade/approve")
async def trade_approve(id: str = Query(..., description="idempotency key or ticket_id")):
    # חיפוש טיקט ב-ConfirmStore (תמיכה לאחור)
    it: Optional[Dict[str, Any]] = None
    try:
        for t in (ConfirmStore.pending() or []):
            if str(t.get("idem") or t.get("ticket_id")) == str(id):
                it = t; break
    except Exception:
        # חלק מהגרסאות מספקות get()
        try:
            it = ConfirmStore.get(id)  # type: ignore
        except Exception:
            it = None

    if not it:
        try:
            record_trade_rejected(symbol="unknown", side="unknown", reason="approve_not_found")
        except Exception:
            pass
        return {"ok": False, "error": "not_found"}

    flow = "HYBRID" if any(it.get(k) for k in ("tp1","tp2","tp3","sl")) else "MARKET"
    res = await (_execute_trade_hybrid(it) if flow=="HYBRID" else _execute_trade_direct(it))
    ok = bool(res.get("ok"))

    try:
        ConfirmStore.decide(str(it.get("ticket_id") or id), approved=ok)
    except Exception:
        pass

    try:
        if ok:
            record_trade_approved(symbol=str(it.get("symbol","")).upper() or "unknown",
                                  side=str(it.get("side","")).upper() or "unknown")
            record_trade_executed(symbol=str(it.get("symbol","")).upper() or "unknown",
                                  side=str(it.get("side","")).upper() or "unknown",
                                  flow=flow, via="approval_link")
        else:
            record_trade_rejected(symbol=str(it.get("symbol","")).upper() or "unknown",
                                  side=str(it.get("side","")).upper() or "unknown",
                                  reason="approve_execute_failed")
    except Exception:
        pass

    return {"ok": ok, "flow": flow, "result": res}

@router.get("/trade/reject")
async def trade_reject(id: str = Query(..., description="idempotency key or ticket_id")):
    try:
        ConfirmStore.decide(str(id), approved=False)
    except Exception:
        pass
    try:
        record_trade_rejected(symbol="unknown", side="unknown", reason="manual_reject")
    except Exception:
        pass
    return {"ok": True, "rejected": True, "id": id}




















































































































































































































































































































































































































































































































































































































































































