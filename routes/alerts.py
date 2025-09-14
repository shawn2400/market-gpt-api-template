# routes/alerts.py
from __future__ import annotations
import os, time
from typing import Optional, Dict, Any, List, Tuple

from fastapi import APIRouter, Depends, Body, Header, HTTPException, Request
from pydantic import BaseModel, Field, constr

from utils.auth import require_api_key
from utils.telegram_api import send_message as telegram_send
from utils.approvals import preflight_proposal

# HMAC + Idempotency
from utils.security import verify_hmac, idem_seen  # NEW

# Rate-limit (אופציונלי)
from utils.rate_limit import require_rate_limit

# Auto-exec כלים (לייב)
from utils.risk import suggest_risk
from utils.binance_client import (
    futures_create_order,
    set_leverage,
    futures_mark_price,
    get_symbol_filters,
    modify_stop_loss,
    place_tp_ladder,
)

# ===== ENV =====
WEBHOOK_HMAC_SECRET = os.getenv("WEBHOOK_HMAC_SECRET", "").strip()
SINK_ENFORCE_APPROVALS = os.getenv("SINK_ENFORCE_APPROVALS", "1").lower() in ("1","true","yes","on")
AUTO_RUN  = os.getenv("AUTO_RUN", "1").lower() in ("1","true","yes","on")
EXECUTE_TRADES = os.getenv("EXECUTE_TRADES", "1").lower() in ("1","true","yes","on")
ORDER_ID_PREFIX = os.getenv("ORDER_ID_PREFIX", "ALG").strip()
ALERTS_RPM = int(os.getenv("ALERTS_RPM", "60"))
ALERTS_BURST = int(os.getenv("ALERTS_BURST", str(ALERTS_RPM)))

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
def _side_to_binance(side: str) -> Tuple[str, str]:
    s = (side or "").strip().lower()
    if s in ("buy","long","up"):  return "BUY", "LONG"
    if s in ("sell","short","down"): return "SELL", "SHORT"
    return "BUY", "LONG"

def _close_side_for_pos(pos_side: str) -> str:
    ps = (pos_side or "").upper()
    return "SELL" if ps == "LONG" else "BUY"

def _decimals_from_step(step_str: str) -> int:
    if "." not in step_str:
        return 0
    frac = step_str.split(".", 1)[1]
    while frac and frac.endswith("0"):
        frac = frac[:-1]
    return len(frac)

def _quantize_qty_with_filters(symbol: str, price: float, qty_guess: float) -> float:
    f = get_symbol_filters(symbol) or {}
    step = float(f.get("stepSize") or 0.001)
    min_notional = float(f.get("minNotional") or 5.0)
    qty = max(qty_guess, min_notional / max(price, 1e-12))
    if step <= 0:
        step = 0.001
    steps = int(qty / step)
    qty_adj = max(step, steps * step)
    return qty_adj

def _targets_from_alert(a: TradeAlert) -> List[float]:
    out = [a.tp1]
    if a.tp2: out.append(a.tp2)
    if a.tp3: out.append(a.tp3)
    return out

def _tp_percents_from_targets(entry_price: float, entry_side: str, tps: List[float]) -> List[float]:
    """
    ממיר יעדי TP ב־Price לאחוזים בהתאם לצד הכניסה.
    BUY: pct = (tp/entry - 1) * 100
    SELL: pct = (1 - tp/entry) * 100
    מסנן יעדים שליליים/שגויים.
    """
    out: List[float] = []
    if entry_price <= 0 or not tps:
        return out
    es = (entry_side or "").upper()
    for tp in tps:
        if tp <= 0:
            continue
        if es == "BUY":
            pct = (tp / entry_price - 1.0) * 100.0
        else:
            pct = (1.0 - tp / entry_price) * 100.0
        if pct > 0:
            out.append(round(pct, 6))
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

# === Auto Execute ===
def _risk_and_open_market(alert: TradeAlert) -> Dict[str, Any]:
    symbol = alert.symbol.upper()
    ex_side, pos_side = _side_to_binance(alert.side)
    price = futures_mark_price(symbol) or float(alert.entry)

    try:
        r = suggest_risk(symbol=symbol, entry=float(alert.entry), sl=float(alert.sl),
                         budget_usd=alert.budget_usd, leverage=alert.leverage)
        leverage = int(r.get("leverage") or alert.leverage or 10)
        budget_usd = float(r.get("budget_usd") or alert.budget_usd or 50.0)
        qty_risk = float(r.get("quantity") or 0.0)
    except Exception:
        leverage = int(alert.leverage or 10)
        budget_usd = float(alert.budget_usd or 50.0)
        qty_risk = (budget_usd * leverage) / max(price, 1e-12)

    qty = _quantize_qty_with_filters(symbol, price, qty_risk)
    lev_resp = set_leverage(symbol, leverage)
    order = futures_create_order(symbol=symbol, side=ex_side, type="MARKET", quantity=str(qty))

    # SL חדש (close_position=True → ייקח כמות מהפוזיציה)
    sl_resp = modify_stop_loss(
        symbol,
        float(alert.sl),
        side=_close_side_for_pos(pos_side),
        close_position=True
    )

    # TP ladder: המרה לאחוזים ושיגור
    tps = _targets_from_alert(alert)
    tp_percents = _tp_percents_from_targets(price, ex_side, tps)
    tp_resp = place_tp_ladder(
        symbol,
        entry_side=ex_side,
        entry_price=float(price),
        quantity=float(qty),
        tp_percents=tp_percents if tp_percents else None
    )

    return {
        "leverage_set": lev_resp,
        "market_order": order,
        "stop_loss": sl_resp,
        "tp_ladder": tp_resp,
        "qty": qty,
        "price_ref": price,
        "pos_side": pos_side,
    }

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
    if approved and AUTO_RUN and EXECUTE_TRADES and (not SINK_ENFORCE_APPROVALS):
        try:
            order_payload = _risk_and_open_market(alert)
            executed = True
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












