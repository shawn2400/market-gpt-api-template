# routes/alerts.py
from __future__ import annotations

import os, time, uuid, inspect
from typing import Optional, Dict, Any, List

from fastapi import APIRouter, Depends, Body, Header, HTTPException, Request
from pydantic import BaseModel, constr

from utils.auth import require_api_key
from utils.rate_limit import require_rate_limit
from utils.security import verify_hmac_multi, idem_seen

# --- Telegram send (שכבה דקה עם fallback) ---
try:
    from utils.telegram_api import send_message as telegram_send
except Exception:
    async def telegram_send(text: str) -> None:
        return None

# --- Approvals preflight (fallback אם חסר מודול) ---
try:
    from utils.approvals import preflight_proposal
except Exception:
    def preflight_proposal(payload: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        return True, None

# --- Trade executor (תמיכה ב-sync/async) ---
from utils.trade_executor import execute_trade_live

async def _exec_trade_adaptive(**kwargs) -> Dict[str, Any]:
    if inspect.iscoroutinefunction(execute_trade_live):
        return await execute_trade_live(**kwargs)  # type: ignore
    return execute_trade_live(**kwargs)  # type: ignore

# ===== ENV =====
WEBHOOK_HMAC_SECRET = os.getenv("WEBHOOK_HMAC_SECRET", "").strip()
SINK_ENFORCE_APPROVALS = os.getenv("SINK_ENFORCE_APPROVALS", "1").lower() in ("1","true","yes","on")
AUTO_RUN = os.getenv("AUTO_RUN", "1").lower() in ("1","true","yes","on")
EXECUTE_TRADES = os.getenv("EXECUTE_TRADES", "1").lower() in ("1","true","yes","on")
ORDER_ID_PREFIX = os.getenv("ORDER_ID_PREFIX", "ALG").strip()

ALERTS_RPM = int(os.getenv("ALERTS_RPM", "60"))
ALERTS_BURST = int(os.getenv("ALERTS_BURST", str(ALERTS_RPM)))

ADMIN_CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID") or os.getenv("ADMIN_CHAT_ID") or "0")

router = APIRouter(
    prefix="/alerts",
    tags=["Alerts"],
    dependencies=[
        Depends(require_api_key),
        Depends(require_rate_limit(ns="alerts", rpm=ALERTS_RPM, burst=ALERTS_BURST, by_token_only=True)),
    ],
)

_ACTIVE: Dict[str, Dict[str, Any]] = {}

# ================= Models =================
class TradeAlert(BaseModel):
    symbol: constr(min_length=3, max_length=20)
    side: constr(strip_whitespace=True)   # buy/sell/long/short
    entry: float
    sl: float
    tp1: float
    tp2: Optional[float] = None
    tp3: Optional[float] = None
    leverage: Optional[int] = 10
    budget_usd: Optional[float] = 50.0
    note: Optional[str] = None
    market: Optional[str] = "futures"
    interval: Optional[str] = "15m"
    chat_id: Optional[int] = None

class AlertResponse(BaseModel):
    ok: bool
    id: Optional[str] = None
    reason: Optional[str] = None
    approved: Optional[bool] = None
    executed: Optional[bool] = None
    order: Optional[Dict[str, Any]] = None

# ================= Helpers =================
def _side_to_ex(side: str) -> str:
    s = (side or "").strip().lower()
    if s in ("buy","long","up"): return "BUY"
    if s in ("sell","short","down"): return "SELL"
    return "BUY"

def _targets_from_alert(a: TradeAlert) -> List[float]:
    out = [a.tp1]
    if a.tp2 is not None: out.append(a.tp2)
    if a.tp3 is not None: out.append(a.tp3)
    return out

async def _notify_new_alert(alert: TradeAlert, approved: bool, reason: Optional[str]) -> None:
    try:
        if ADMIN_CHAT_ID <= 0: return
        tps = ", ".join(str(x) for x in _targets_from_alert(alert))
        text = (
            f"📢 Alert\n"
            f"{alert.symbol.upper()} {alert.side.upper()}\n"
            f"Entry={alert.entry}, SL={alert.sl}, TP(s)=[{tps}]\n"
            f"Approved={approved}  Reason={reason or '-'}"
        )
        await telegram_send(text)
    except Exception:
        pass

def _mk_id(base: Optional[str] = None) -> str:
    return base or f"t_{int(time.time())}_{uuid.uuid4().hex[:8]}"

# ================= Routes =================
@router.post("/trades/active", response_model=AlertResponse)
async def receive_alert(
    alert: TradeAlert,
    request: Request,
    x_signature: Optional[str] = Header(None),
    x_webhook_hmac: Optional[str] = Header(None),
    x_hub_signature_256: Optional[str] = Header(None),
    x_idempotency_key: Optional[str] = Header(None),
) -> AlertResponse:
    # אימות HMAC (אם יש secret) — multi-headers לחישוב אחיד
    if WEBHOOK_HMAC_SECRET:
        raw = await request.body()
        if not verify_hmac_multi(raw, x_signature, x_webhook_hmac, x_hub_signature_256):
            raise HTTPException(status_code=401, detail="Invalid HMAC signature")

    if x_idempotency_key and idem_seen(x_idempotency_key):
        alert_id = x_idempotency_key
        existing = _ACTIVE.get(alert_id)
        if existing:
            return AlertResponse(
                ok=True,
                id=alert_id,
                approved=bool(existing.get("approved")),
                executed=bool(existing.get("executed")),
                reason="duplicate",
            )

    approved: bool = True
    reason: Optional[str] = None
    if SINK_ENFORCE_APPROVALS:
        try:
            approved, reason = preflight_proposal(alert.dict())
        except Exception as e:
            approved, reason = False, f"preflight_failed: {e}"

    await _notify_new_alert(alert, approved, reason)

    alert_id = _mk_id(x_idempotency_key)
    payload = {
        **alert.dict(),
        "id": alert_id,
        "ts": time.time(),
        "approved": approved,
        "executed": False,
        "source": "active",
        "idempotency": x_idempotency_key,
    }
    _ACTIVE[alert_id] = payload

    executed = False
    order_payload: Optional[Dict[str, Any]] = None
    if approved and AUTO_RUN and EXECUTE_TRADES:
        try:
            tp_targets = _targets_from_alert(alert)
            res = await _exec_trade_adaptive(
                symbol=alert.symbol.upper(),
                side=_side_to_ex(alert.side),
                leverage=int(alert.leverage or 10),
                budget=float(alert.budget_usd or 50.0),
                dry_run=False,
                entry=float(alert.entry),
                sl=float(alert.sl),
                tp=None,
                tp_targets=tp_targets if tp_targets else None,
                confirm_first=True,
                telegram_chat_id=alert.chat_id or (ADMIN_CHAT_ID or None),
            )
            order_payload = res
            executed = bool(res and res.get("ok", False))
            payload["executed"] = executed
            if not executed:
                reason = res.get("reason") or "execute_trade_live_failed"
        except Exception as e:
            reason = f"auto_exec_failed: {e}"

    return AlertResponse(ok=True, id=alert_id, approved=approved, reason=reason, executed=executed, order=order_payload)

@router.get("/trades/active")
def list_active_trades() -> Dict[str, Any]:
    return {"ok": True, "count": len(_ACTIVE), "items": _ACTIVE}

@router.post("/trades/update", response_model=Dict[str, Any])
async def update_trade_status(
    payload: Dict[str, Any] = Body(...),
    x_signature: Optional[str] = Header(None),
    x_idempotency_key: Optional[str] = Header(None),
) -> Dict[str, Any]:
    trade_id = payload.get("id") or payload.get("trade_id")
    if not trade_id:
        raise HTTPException(status_code=422, detail="missing trade id")

    item = _ACTIVE.get(trade_id)
    if not item:
        raise HTTPException(status_code=404, detail="Trade not found")

    updates = payload.get("updates")
    if isinstance(updates, dict):
        for k, v in updates.items():
            if k in ("approved", "executed"):
                item[k] = bool(v)
            else:
                if "alert" in item and isinstance(item["alert"], dict):
                    item["alert"][k] = v
                else:
                    item[k] = v
    else:
        for k in ("approved","executed","entry","sl","tp1","tp2","tp3","leverage","budget_usd","note"):
            if k in payload:
                item[k] = bool(payload[k]) if k in ("approved","executed") else payload[k]

    _ACTIVE[trade_id] = item
    return {"ok": True, "id": trade_id, "item": item}

@router.post("/analysis")
async def receive_analysis(
    request: Request,
    payload: Dict[str, Any] = Body(...),
    x_signature: Optional[str] = Header(None),
    x_webhook_hmac: Optional[str] = Header(None),
    x_hub_signature_256: Optional[str] = Header(None),
) -> Dict[str, Any]:
    if WEBHOOK_HMAC_SECRET:
        raw = await request.body()
        if not verify_hmac_multi(raw, x_signature, x_webhook_hmac, x_hub_signature_256):
            raise HTTPException(status_code=401, detail="Invalid HMAC signature")
    try:
        if ADMIN_CHAT_ID > 0:
            await telegram_send(f"📊 ניתוח התקבל:\n{payload}")
    except Exception:
        pass
    return {"ok": True}

@router.post("/trade-ingest")
async def ingest_trade(
    request: Request,
    payload: Dict[str, Any] = Body(...),
    x_signature: Optional[str] = Header(None),
    x_webhook_hmac: Optional[str] = Header(None),
    x_hub_signature_256: Optional[str] = Header(None),
    x_idempotency_key: Optional[str] = Header(None),
) -> Dict[str, Any]:
    if WEBHOOK_HMAC_SECRET:
        raw = await request.body()
        if not verify_hmac_multi(raw, x_signature, x_webhook_hmac, x_hub_signature_256):
            raise HTTPException(status_code=401, detail="Invalid HMAC signature")

    if x_idempotency_key and idem_seen(x_idempotency_key):
        return {"ok": True, "duplicate": True, "trade_id": x_idempotency_key}

    trade_id = payload.get("trade_id") or payload.get("id") or _mk_id(x_idempotency_key)

    item = {
        "id": trade_id,
        "trade_id": trade_id,
        "ts": time.time(),
        "approved": False,
        "executed": False,
        "source": "ingest",
        "idempotency": x_idempotency_key,
        "alert": payload,
    }
    _ACTIVE[trade_id] = item
    return {"ok": True, "trade_id": trade_id, "chat_id": payload.get("chat_id")}


















