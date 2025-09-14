# routes/alerts.py
from __future__ import annotations
import os, time
from typing import Optional, Dict, Any, List, Tuple

from fastapi import APIRouter, Depends, Body, Header, HTTPException, Request
from pydantic import BaseModel, Field, constr

from utils.auth import require_api_key
from utils.telegram_api import send_message as telegram_send
from utils.approvals import preflight_proposal
from utils.security import verify_hmac, idem_seen
from utils.rate_limit import require_rate_limit

# ביצוע לייב עם אישור בטלגרם
from utils.trade_executor import execute_trade_live

# ===== ENV =====
WEBHOOK_HMAC_SECRET = os.getenv("WEBHOOK_HMAC_SECRET", "").strip()
SINK_ENFORCE_APPROVALS = os.getenv("SINK_ENFORCE_APPROVALS", "1").lower() in ("1","true","yes","on")
AUTO_RUN  = os.getenv("AUTO_RUN", "1").lower() in ("1","true","yes","on")
EXECUTE_TRADES = os.getenv("EXECUTE_TRADES", "1").lower() in ("1","true","yes","on")

ORDER_ID_PREFIX = os.getenv("ORDER_ID_PREFIX", "ALG").strip()

ALERTS_RPM = int(os.getenv("ALERTS_RPM", "60"))
ALERTS_BURST = int(os.getenv("ALERTS_BURST", str(ALERTS_RPM)))

# צ'אט ברירת מחדל לאישור בטלגרם
ADMIN_CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID") or os.getenv("ADMIN_CHAT_ID") or "0")

router = APIRouter(
    prefix="/alerts",
    tags=["Alerts"],
    dependencies=[
        Depends(require_api_key),
        Depends(require_rate_limit(ns="alerts", rpm=ALERTS_RPM, burst=ALERTS_BURST, by_token_only=True)),
    ],
)

# ===== In-memory store (סטטוס אזעקות פעילות) =====
_ACTIVE: Dict[str, Dict[str, Any]] = {}

# ================= Models =================
class TradeAlert(BaseModel):
    symbol: constr(min_length=3, max_length=20)
    side: constr(strip_whitespace=True)  # buy/sell/long/short
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
    executed: Optional[bool] = None
    order: Optional[Dict[str, Any]] = None

# ================= Helpers =================
def _side_to_ex(side: str) -> str:
    s = (side or "").strip().lower()
    if s in ("buy","long","up"):  return "BUY"
    if s in ("sell","short","down"): return "SELL"
    return "BUY"

def _targets_from_alert(a: TradeAlert) -> List[float]:
    out = [a.tp1]
    if a.tp2: out.append(a.tp2)
    if a.tp3: out.append(a.tp3)
    return out

async def _notify_new_alert(alert: TradeAlert, approved: bool, reason: Optional[str]) -> None:
    try:
        tps = ", ".join(str(x) for x in _targets_from_alert(alert))
        text = (
            f"📢 Alert\n"
            f"{alert.symbol} {alert.side.upper()}\n"
            f"Entry={alert.entry}, SL={alert.sl}, TP(s)=[{tps}]\n"
            f"Approved={approved}  Reason={reason or '-'}"
        )
        await telegram_send(text)
    except Exception:
        pass

# ================= Routes =================
@router.post("/trades/active", response_model=AlertResponse)
async def receive_alert(
    alert: TradeAlert,
    request: Request,
    x_signature: Optional[str] = Header(None),
    x_idempotency_key: Optional[str] = Header(None),
) -> AlertResponse:
    # אימות HMAC (אם יש סוד בקונפיג)
    if WEBHOOK_HMAC_SECRET:
        raw = await request.body()
        if not verify_hmac(x_signature, raw):
            raise HTTPException(status_code=401, detail="Invalid HMAC signature")

    # Idempotency (מניעת כפילויות)
    if x_idempotency_key and idem_seen(x_idempotency_key):
        return AlertResponse(ok=True, id=x_idempotency_key, approved=True, reason="duplicate", executed=False)

    # אישור מקדים (SOP/Guard)
    approved, reason = True, None
    if SINK_ENFORCE_APPROVALS:
        approved, reason = preflight_proposal(alert.dict())

    await _notify_new_alert(alert, approved, reason)

    alert_id = x_idempotency_key or f"{alert.symbol}-{int(time.time()*1000)}"
    _ACTIVE[alert_id] = {**alert.dict(), "ts": time.time(), "approved": approved}

    executed = False
    order_payload: Optional[Dict[str, Any]] = None

    if approved and AUTO_RUN and EXECUTE_TRADES:
        # מבצעים דרך המנוע המאוחד — תמיד עם אישור בטלגרם
        try:
            tp_targets = _targets_from_alert(alert)  # TP כמחירי יעד (לא אחוזים)
            res = await execute_trade_live(
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
                telegram_chat_id=ADMIN_CHAT_ID or None,
            )
            order_payload = res
            executed = bool(res and res.get("ok", False))
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
    # (אופציונלי) אימות חתימה אם FE מעביר חתימה
    trade_id = payload.get("id")
    if not trade_id or trade_id not in _ACTIVE:
        raise HTTPException(status_code=404, detail="Trade not found")
    _ACTIVE[trade_id].update(payload)
    return {"ok": True, "id": trade_id, "item": _ACTIVE[trade_id]}

@router.post("/analysis")
async def receive_analysis(
    request: Request,
    payload: Dict[str, Any] = Body(...),
    x_signature: Optional[str] = Header(None),
) -> Dict[str, Any]:
    if WEBHOOK_HMAC_SECRET:
        raw = await request.body()
        if not verify_hmac(x_signature, raw):
            raise HTTPException(status_code=401, detail="Invalid HMAC signature")
    try:
        await telegram_send(f"📊 ניתוח התקבל:\n{payload}")
    except Exception:
        pass
    return {"ok": True}

@router.post("/trade-ingest")
async def ingest_trade(
    request: Request,
    payload: Dict[str, Any] = Body(...),
    x_signature: Optional[str] = Header(None),
    x_idempotency_key: Optional[str] = Header(None),
) -> Dict[str, Any]:
    if WEBHOOK_HMAC_SECRET:
        raw = await request.body()
        if not verify_hmac(x_signature, raw):
            raise HTTPException(status_code=401, detail="Invalid HMAC signature")
    if x_idempotency_key and idem_seen(x_idempotency_key):
        return {"ok": True, "duplicate": True}
    return {"ok": True, "payload": payload}













