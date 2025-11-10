# /app/routes/trade.py
from __future__ import annotations
import os, time, logging, inspect, re, asyncio, json, hashlib
from typing import Any, Dict, Optional, List, Callable

from fastapi import APIRouter, Header, HTTPException, Request, Body, Query, Depends
from pydantic import BaseModel

# --- Pydantic v1/v2 compatibility for validators & config ---
try:
    # Pydantic v2
    from pydantic import field_validator as _field_validator  # type: ignore
    from pydantic import model_validator as _model_validator  # type: ignore

    def FIELD_VALIDATOR(*fields, **kwargs):
        return _field_validator(*fields, **kwargs)

    def ROOT_VALIDATOR(**kwargs):
        return _model_validator(mode="after")

    _EXTRA_IGNORE_CONFIG = {"extra": "ignore"}  # ignore unknown fields in JSON
except Exception:
    # Pydantic v1
    from pydantic import validator as _validator  # type: ignore
    from pydantic import root_validator as _root_validator  # type: ignore

    def FIELD_VALIDATOR(*fields, **kwargs):
        return _validator(*fields, **kwargs)

    def ROOT_VALIDATOR(**kwargs):
        return _root_validator(**kwargs)

    class _Cfg:  # pydantic v1 style
        extra = "ignore"
    _EXTRA_IGNORE_CONFIG = {"Config": _Cfg}

# --- Router + Auth dependency (optional) ---
try:
    from utils.auth import require_api_key
    _router_deps = [Depends(require_api_key)]
except Exception:
    _router_deps = []

logger = logging.getLogger("algogpt.trade")
router = APIRouter(prefix="/trade", tags=["trade"], dependencies=_router_deps)

# ---------- metrics wiring (optional) ----------
try:
    from routes.metrics import (
        record_trade_request, record_trade_ok, record_trade_fail, record_trade_approval
    )
except Exception:
    def record_trade_request(flow: Optional[str] = None):  # type: ignore
        pass
    def record_trade_ok(flow: Optional[str] = None):  # type: ignore
        pass
    def record_trade_fail(flow: Optional[str] = None):  # type: ignore
        pass
    def record_trade_approval(action: str, ok: bool):  # type: ignore
        pass

from utils.metrics import METRICS

try:
    from utils.risk import can_execute_trade, note_trade_execution, evaluate_trade_request  # type: ignore
except Exception:  # pragma: no cover - graceful degradation
    def can_execute_trade(symbol: str, now: Optional[float] = None):  # type: ignore
        return {"ok": True}
    def note_trade_execution(symbol: str, now: Optional[float] = None) -> None:  # type: ignore
        return None
    def evaluate_trade_request(**_kwargs: Any):  # type: ignore
        return {"ok": True}

try:
    from utils.binance_client import get_klines_df  # type: ignore
except Exception:
    get_klines_df = None  # type: ignore

try:
    from utils.indicators import ema  # type: ignore
except Exception:
    ema = None  # type: ignore

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

# --------- COID builder (מרכזי עם fallback) ----------
try:
    from utils.order_ids import build_client_order_id  # type: ignore
except Exception:
    _SAFE = re.compile(r'[^A-Za-z0-9._:/-]')

    def build_client_order_id(symbol: str, side: str, role: str = "ENTRY") -> str:  # type: ignore
        pref = (os.getenv("ORDER_ID_PREFIX") or "ALG").strip() or "ALG"
        ts = int(time.time() * 1000)
        raw = f"{pref}-{str(symbol).upper()}-{str(side).upper()}-{str(role).upper()}-{ts}"
        s = _SAFE.sub("_", raw)
        if len(s) <= 36:
            return s
        h = hashlib.md5(s.encode("utf-8")).hexdigest()[:6]
        return f"{s[:36 - (len(h) + 1)]}_{h}"

# --------- helpers ----------
def _hedge_mode_enabled() -> bool:
    if os.getenv("POSITION_MODE_OVERRIDE", "").strip().lower() in ("hedge", "hedged"):
        return True
    if os.getenv("BINANCE_FORCE_HEDGE_MODE", "").strip().lower() in ("1", "true", "yes", "on"):
        return True
    return False

def _is_code_4061(err: Exception | str) -> bool:
    s = str(err)
    return "code=-4061" in s or "position side does not match" in s.lower()

def _filter_kwargs_for_callable(fn: Callable[..., Any], kwargs: Dict[str, Any]) -> Dict[str, Any]:
    try:
        sig = inspect.signature(fn)
        allowed = set(sig.parameters.keys())
        return {k: v for k, v in kwargs.items() if k in allowed and v is not None}
    except Exception:
        bad = {"tp_kind", "sl_kind", "entry_kind", "entry_offset", "tp_offset", "sl_offset"}
        return {k: v for k, v in kwargs.items() if k not in bad and v is not None}

def _btc_gate_allows(side: str) -> bool:
    if get_klines_df is None or ema is None:
        return True
    try:
        df = get_klines_df("BTCUSDT", interval="15m", limit=60)
        if df is None or getattr(df, "empty", False):
            return True
        closes = df["close"].astype(float)
        ema_series = ema(closes, 50)
        if ema_series is None or getattr(ema_series, "empty", False):
            return True
        ema_val = float(ema_series.iloc[-1])
        price_val = float(closes.iloc[-1])
        if side.upper() == "BUY":
            return price_val >= ema_val
        if side.upper() == "SELL":
            return price_val <= ema_val
    except Exception as exc:
        logger.debug("btc_gate_eval_failed: %s", exc)
        return True
    return True

# --------- execution paths ----------
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
        api_key = os.getenv("BINANCE_API_KEY", "").strip()
        api_sec = os.getenv("BINANCE_API_SECRET", "").strip()
        if not (api_key and api_sec):
            return {"ok": False, "error": "binance_keys_missing"}
        client = Client(api_key, api_sec)

        symbol = str(ticket.get("symbol", "")).upper()
        side = str(ticket.get("side", "")).upper()
        qty = float(ticket.get("qty") or ticket.get("quantity") or 0)
        leverage = int(ticket.get("leverage") or 0)
        if not (symbol and side in ("BUY", "SELL") and qty > 0 and leverage > 0):
            return {"ok": False, "error": "bad_ticket_params"}

        # עדכון מינוף (best-effort)
        try:
            client.futures_change_leverage(symbol=symbol, leverage=leverage)
        except Exception as e:
            logger.warning("futures_change_leverage failed: %s", e)

        base_kwargs: Dict[str, Any] = {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quantity": qty,
            "newClientOrderId": build_client_order_id(symbol, side, role="ENTRY"),
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
                return {
                    "ok": False,
                    "error": "order_failed",
                    "detail": str(e2),
                    "first_error": str(e1),
                }
    except Exception as e:
        logger.error("order_execute_direct_failed: %s", e)
        return {"ok": False, "error": "order_failed", "detail": str(e)}

async def _execute_trade_hybrid(ticket: Dict[str, Any]) -> Dict[str, Any]:
    # העדפת מתאם חי (עם ניהול TP/SL וכו')
    exec_live = None
    exec_live_async = None
    try:
        from utils.trade_executor import execute_trade_live as _live  # type: ignore
        exec_live = _live
    except Exception:
        pass
    try:
        from utils.trade_executor import execute_trade_live_async as _live_async  # type: ignore
        exec_live_async = _live_async
    except Exception:
        pass

    if exec_live_async is None and exec_live is None:
        return {"ok": False, "error": "execute_trade_live_missing"}

    symbol = str(ticket.get("symbol", "")).upper()
    side = str(ticket.get("side", "")).upper()
    qty = ticket.get("qty") or ticket.get("quantity")
    leverage = int(ticket.get("leverage") or ticket.get("lev") or 0)
    pos_side = str(
        ticket.get("position_side") or ticket.get("positionSide") or ("LONG" if side == "BUY" else "SHORT")
    ).upper()

    tps_raw = [ticket.get("tp1"), ticket.get("tp2"), ticket.get("tp3")]
    tp_targets = [float(x) for x in tps_raw if x is not None and str(x) not in ("0", "0.0") and float(x) > 0]
    sl_targets = [float(ticket.get("sl"))] if (ticket.get("sl") not in (None, 0, "0", "0.0")) else None

    if not (symbol and side in ("BUY", "SELL") and leverage > 0):
        return {"ok": False, "error": "bad_ticket_params"}

    base_kwargs: Dict[str, Any] = dict(
        symbol=symbol,
        side=side,
        budget=ticket.get("budget") or ticket.get("budget_usd"),
        leverage=leverage,
        dry_run=bool(ticket.get("dry_run", False)),
        quantity=(float(qty) if qty is not None else None),
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

    if exec_live_async is not None:
        try:
            return await exec_live_async(base_kwargs)
        except TypeError:
            clean = _filter_kwargs_for_callable(exec_live_async, base_kwargs)
            return await exec_live_async(clean)

    # fallback: exec_live sync
    clean = _filter_kwargs_for_callable(exec_live, base_kwargs)  # type: ignore[arg-type]
    if inspect.iscoroutinefunction(exec_live):  # type: ignore[arg-type]
        return await exec_live(**clean)  # type: ignore[misc]
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: exec_live(**clean))  # type: ignore[misc]

def _choose_flow(req: "TradeRequest") -> str:
    if any(x is not None for x in (req.tp1, req.tp2, req.tp3, req.sl)):
        return "HYBRID"
    if (req.quantity is None) and (req.budget_usd is not None):
        return "HYBRID"
    return "MARKET"

# --------- Schemas ----------
class TradeRequest(BaseModel):
    symbol: str
    side: str
    quantity: Optional[float] = None
    leverage: int
    budget_usd: Optional[float] = None
    confirm_first: bool = False              # legacy flag to force approval
    require_approval: bool = False           # explicit flag; default False => no ops ticket
    note: Optional[str] = None
    tp1: Optional[float] = None
    tp2: Optional[float] = None
    tp3: Optional[float] = None
    sl: Optional[float] = None
    tp_splits: Optional[List[float]] = None
    position_side: Optional[str] = None      # "LONG"/"SHORT"
    positionSide: Optional[str] = None       # alias from clients
    reduce_only: Optional[bool] = False

    # allow extra keys (e.g. "approval", "tp_sl_mode", etc.) without failing
    # Pydantic v2: model_config; v1: Config class above
    if "extra" in _EXTRA_IGNORE_CONFIG:
        model_config = _EXTRA_IGNORE_CONFIG  # type: ignore[attr-defined]
    else:
        Config = _EXTRA_IGNORE_CONFIG["Config"]  # type: ignore[misc, assignment]

    @FIELD_VALIDATOR("symbol")
    @classmethod
    def _sym_upper(cls, v: str) -> str:
        v = (v or "").strip().upper()
        if not v:
            raise ValueError("symbol required")
        return v

    @FIELD_VALIDATOR("side")
    @classmethod
    def _side_upper(cls, v: str) -> str:
        v = (v or "").strip().upper()
        if v not in ("BUY", "SELL"):
            raise ValueError("side must be BUY/SELL")
        return v

    @FIELD_VALIDATOR("leverage")
    @classmethod
    def _lev_pos(cls, v: int) -> int:
        iv = int(v or 0)
        if iv <= 0:
            raise ValueError("leverage must be > 0")
        return iv

    @ROOT_VALIDATOR()
    def _normalize_and_require_qty_or_budget(self):  # type: ignore[no-redef]
        # Normalize position_side alias
        ps = getattr(self, "position_side", None)
        ps_alias = getattr(self, "positionSide", None)
        if not ps and ps_alias:
            self.position_side = ps_alias

        # Require either positive quantity or positive budget
        q = getattr(self, "quantity", None)
        b = getattr(self, "budget_usd", None)
        if (q is None or float(q) <= 0) and (b is None or float(b) <= 0):
            raise ValueError("Provide positive quantity or positive budget_usd")
        return self

# --------- Routes ----------
@router.post("/execute")
async def trade_execute(
    request: Request,
    req: TradeRequest = Body(...),
    x_idempotency_key: Optional[str] = Header(default=None, alias="X-Idempotency-Key"),
):
    flow = _choose_flow(req)
    record_trade_request(flow)

    # Global toggle may force approvals
    force_approve_env = os.getenv("REQUIRE_TELEGRAM_APPROVAL", "0").lower() in ("1", "true", "yes", "on")
    # Respect explicit require_approval or legacy confirm_first
    need_approval = bool(req.require_approval or req.confirm_first or force_approve_env)

    # === Approval Gate ===
    if need_approval:
        try:
            import httpx
            public_host = os.getenv("PUBLIC_HOST", "").strip()
            base = public_host if public_host else str(request.base_url).rstrip("/")
            payload = {
                "symbol": req.symbol,
                "side": req.side,
                "qty": (req.quantity if req.quantity is not None else None),
                "leverage": req.leverage,
                "tp1": req.tp1,
                "tp2": req.tp2,
                "tp3": req.tp3,
                "sl": req.sl,
                "tp_splits": req.tp_splits,
                "budget": req.budget_usd,
                "position_side": (req.position_side or ("LONG" if req.side == "BUY" else "SHORT")).upper(),
                "note": req.note or "",
            }
            headers: Dict[str, str] = {}
            api_key = (
                os.getenv("API_TOKEN")
                or os.getenv("PRIMARY_API_TOKEN")
                or os.getenv("API_BEARER_TOKEN")
                or os.getenv("ALGOGPT_API_TOKEN")
            )
            if api_key:
                headers["X-API-Key"] = api_key.strip()
            if x_idempotency_key:
                headers["X-Idempotency-Key"] = x_idempotency_key
            async with httpx.AsyncClient(timeout=12.0) as cli:
                r = await cli.post(f"{base.rstrip('/')}/ops/ticket", json=payload, headers=headers)
            # defensive JSON parse
            try:
                data = r.json()
            except Exception as e:
                logger.warning("ops_ticket_non_json_or_empty: %s", e)
                data = {"ok": False, "error": "non_json_ticket"}
            if not data.get("ok"):
                raise RuntimeError(f"ops.ticket failed: {data}")
            return {
                "ok": False,
                "error": "pending_approval",
                "result": {
                    "reason": "pending",
                    "ticket_id": data.get("ticket_id"),
                    "approve_url": data.get("approve_url"),
                    "reject_url": data.get("reject_url"),
                    "preview_url": data.get("preview_url"),
                    "ttl_sec": int(os.getenv("OPS_TICKET_TTL_SEC", "1800")),
                },
            }
        except Exception as e:
            logger.error("open_ops_ticket_failed: %s", e)
            record_trade_fail(flow)
            # Preserve behavior ONLY when approval was actually required
            raise HTTPException(status_code=502, detail=f"open_ops_ticket_failed: {e}")

    # === No approval path ===
    if flow == "MARKET" and (req.quantity is None or float(req.quantity) <= 0):
        # if MARKET but no qty -> promote to HYBRID (budget-based execution)
        flow = "HYBRID"

    gate_info = can_execute_trade(req.symbol)
    if not gate_info.get("ok", True):
        reason = gate_info.get("reason", "blocked")
        METRICS.risk_block.labels(reason=reason).inc()
        raise HTTPException(status_code=429, detail=gate_info)

    if not _btc_gate_allows(req.side):
        METRICS.risk_block.labels(reason="btc_gate").inc()
        raise HTTPException(status_code=409, detail={"ok": False, "reason": "btc_gate"})

    ticket_exec = dict(
        symbol=req.symbol,
        side=req.side,
        qty=(req.quantity if req.quantity is not None else None),
        leverage=req.leverage,
        note=req.note or "",
        tp1=req.tp1,
        tp2=req.tp2,
        tp3=req.tp3,
        sl=req.sl,
        tp_splits=req.tp_splits,
        budget=req.budget_usd,
        position_side=(req.position_side or ("LONG" if req.side == "BUY" else "SHORT")).upper(),
        reduce_only=bool(req.reduce_only),
    )

    if flow == "MARKET":
        if ticket_exec.get("qty") is None or float(ticket_exec["qty"]) <= 0:
            record_trade_fail(flow)
            raise HTTPException(status_code=400, detail="quantity required for MARKET flow")

    risk_eval = evaluate_trade_request(
        symbol=req.symbol,
        side=req.side,
        entry_price=None,
        stop_price=req.sl,
        quantity=(float(ticket_exec["qty"]) if ticket_exec.get("qty") is not None else None),
        leverage=req.leverage,
        budget_usd=req.budget_usd,
    )
    if not risk_eval.get("ok", True):
        reason = risk_eval.get("reason", "risk_block")
        METRICS.risk_block.labels(reason=reason).inc()
        raise HTTPException(status_code=409, detail=risk_eval)

    res = await (_execute_trade_direct(ticket_exec) if flow == "MARKET" else _execute_trade_hybrid(ticket_exec))
    ok = bool(res.get("ok"))
    (record_trade_ok if ok else record_trade_fail)(flow)
    if ok:
        note_trade_execution(req.symbol)
    return {"ok": ok, "flow": flow, "result": res}

@router.get("/approve")
async def trade_approve(id: str = Query(..., description="idempotency key or ticket_id")):
    it: Optional[Dict[str, Any]] = None
    try:
        for t in (ConfirmStore.pending() or []):
            if str(t.get("idem") or t.get("ticket_id")) == str(id):
                it = t
                break
    except Exception:
        try:
            it = ConfirmStore.get(id)  # type: ignore
        except Exception:
            it = None

    if not it:
        record_trade_approval("approve", False)
        return {"ok": False, "error": "not_found"}

    flow = "HYBRID" if any(it.get(k) for k in ("tp1", "tp2", "tp3", "sl")) or (it.get("budget") is not None) else "MARKET"
    symbol = str(it.get("symbol") or "").upper()
    side = str(it.get("side") or ("BUY" if it.get("position_side", "LONG").upper() == "LONG" else "SELL")).upper()

    gate_info = can_execute_trade(symbol)
    if not gate_info.get("ok", True):
        reason = gate_info.get("reason", "blocked")
        METRICS.risk_block.labels(reason=reason).inc()
        return {"ok": False, "error": "risk_block", "detail": gate_info}

    if not _btc_gate_allows(side):
        METRICS.risk_block.labels(reason="btc_gate").inc()
        return {"ok": False, "error": "btc_gate"}

    risk_eval = evaluate_trade_request(
        symbol=symbol,
        side=side,
        entry_price=it.get("entry") or it.get("entry_price") or it.get("price"),
        stop_price=it.get("sl"),
        quantity=(float(it.get("qty") or it.get("quantity") or 0) or None),
        leverage=float(it.get("leverage") or it.get("lev") or 1),
        budget_usd=it.get("budget") or it.get("budget_usd"),
    )
    if not risk_eval.get("ok", True):
        reason = risk_eval.get("reason", "risk_block")
        METRICS.risk_block.labels(reason=reason).inc()
        return {"ok": False, "error": "risk_block", "detail": risk_eval}

    res = await (_execute_trade_hybrid(it) if flow == "HYBRID" else _execute_trade_direct(it))
    ok = bool(res.get("ok"))

    try:
        ConfirmStore.decide(str(it.get("ticket_id") or id), approved=ok)
    except Exception:
        pass

    record_trade_approval("approve", ok)
    (record_trade_ok if ok else record_trade_fail)(flow)
    if ok:
        note_trade_execution(symbol)

    return {"ok": ok, "flow": flow, "result": res}

@router.get("/reject")
async def trade_reject(id: str = Query(..., description="idempotency key or ticket_id")):
    try:
        ConfirmStore.decide(str(id), approved=False)
        ok = True
    except Exception:
        ok = False
    record_trade_approval("reject", ok)
    record_trade_fail("HYBRID")
    return {"ok": True, "rejected": True, "id": id}



















































































































































































































































































































































































































































































































































































































































































