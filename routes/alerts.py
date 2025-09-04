# routes/alerts.py
from __future__ import annotations
from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, Body, Header, HTTPException, Request
from pydantic import BaseModel, Field, constr
import os, time

from utils.auth import require_api_key
from utils.telegram_api import send_message as telegram_send
from utils.hmac_utils import verify_inbound
from utils.approvals import preflight_proposal

router = APIRouter(
    prefix="/alerts",
    tags=["Alerts"],
    dependencies=[Depends(require_api_key)],
)

WEBHOOK_HMAC_SECRET = os.getenv("WEBHOOK_HMAC_SECRET", "").strip()
SINK_ENFORCE_APPROVALS = str(os.getenv("SINK_ENFORCE_APPROVALS", "1")).lower() in ("1", "true", "yes", "on")

_ACTIVE: Dict[str, Dict[str, Any]] = {}

# ================= Models =================
class TradeAlert(BaseModel):
    symbol: constr(min_length=3, max_length=20)
    side: constr(to_lower=True, strip_whitespace=True)
    entry: float
    sl: float
    tp1: float
    tp2: Optional[float] = None
    tp3: Optional[float] = None
    leverage: Optional[int] = 10
    budget_usd: Optional[float] = 50.0
    note: Optional[str] = None

class AlertResponse(BaseModel):
    ok: bool
    id: Optional[str] = None
    reason: Optional[str] = None
    approved: Optional[bool] = None

# ================= Routes =================
@router.post("/trades/active", response_model=AlertResponse)
async def receive_alert(
    alert: TradeAlert,
    request: Request,
    x_signature: Optional[str] = Header(None),
) -> AlertResponse:
    if WEBHOOK_HMAC_SECRET:
        body = (await request.body()).decode("utf-8")
        if not verify_inbound(body, x_signature, WEBHOOK_HMAC_SECRET):
            raise HTTPException(status_code=401, detail="Invalid HMAC signature")

    approved, reason = True, None
    if SINK_ENFORCE_APPROVALS:
        approved, reason = preflight_proposal(alert.dict())

    try:
        text = f"📢 *Alert* — {alert.symbol} {alert.side.upper()}\nEntry={alert.entry}, SL={alert.sl}, TP1={alert.tp1}"
        await telegram_send(text)
    except Exception as e:
        reason = f"telegram_error: {e}"

    alert_id = f"{alert.symbol}-{int(time.time())}"
    _ACTIVE[alert_id] = {**alert.dict(), "ts": time.time()}

    return AlertResponse(ok=True, id=alert_id, approved=approved, reason=reason)

@router.get("/trades/active")
def list_active_trades() -> Dict[str, Any]:
    return {"ok": True, "count": len(_ACTIVE), "items": _ACTIVE}

@router.post("/trades/update", response_model=Dict[str, Any])
async def update_trade_status(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    trade_id = payload.get("id")
    if not trade_id or trade_id not in _ACTIVE:
        raise HTTPException(status_code=404, detail="Trade not found")
    _ACTIVE[trade_id].update(payload)
    return {"ok": True, "id": trade_id, "item": _ACTIVE[trade_id]}

@router.post("/analysis")
async def receive_analysis(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    try:
        await telegram_send(f"📊 ניתוח התקבל:\n{payload}")
    except Exception:
        pass
    return {"ok": True}

@router.post("/trade-ingest")
async def ingest_trade(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    return {"ok": True, "payload": payload}









