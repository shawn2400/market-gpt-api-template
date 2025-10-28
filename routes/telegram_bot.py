# routes/telegram_bot.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import json
import logging
from typing import Optional, Dict, Any

import httpx
from fastapi import APIRouter, HTTPException, Query, Request

logger = logging.getLogger("algogpt.routes.telegram_bot")

router = APIRouter(prefix="/telegram", tags=["Telegram"])

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else ""
DEFAULT_CHAT = os.getenv("TELEGRAM_TEST_CHAT_ID", "").strip()
PM_ENV: Optional[str] = (os.getenv("TELEGRAM_PARSE_MODE", "").strip() or None)
WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
PUBLIC_HOST = os.getenv("PUBLIC_HOST", "").strip()

# Optional runtime counters (safe fallbacks)
try:
    from utils.runtime_counters import ws_get_counters as _ws_get_counters  # type: ignore
except Exception:
    def _ws_get_counters() -> Dict[str, Any]:  # type: ignore
        return {"ws_up": 0, "reconnects": 0, "ewma_latency_ms": 0.0, "last_event_age_sec": None}

try:
    from utils.runtime_counters import exec_get_counters as _exec_get_counters  # type: ignore
except Exception:
    def _exec_get_counters() -> Dict[str, Any]:  # type: ignore
        return {
            "tick_ewma_ms": 0.0, "tick_p95_ms": None, "tick_p99_ms": None,
            "last_tick_age_sec": None, "timeouts_burst": 0,
            "no_trade_streak": 0, "current_interval": 0,
        }

# Try to import live executor; otherwise provide shim
try:
    from utils.trade_executor import execute_trade_live  # type: ignore
except Exception:
    async def execute_trade_live(**kwargs):
        return {"ok": True, "mode": "shim", "kwargs": kwargs}


# ===================== Models =====================
try:
    from pydantic import BaseModel, Field, ConfigDict
    _PYD_V2 = True
except Exception:
    from pydantic import BaseModel, Field  # type: ignore
    _PYD_V2 = False


if _PYD_V2:
    class SendRequest(BaseModel):
        model_config = ConfigDict(extra="ignore", populate_by_name=True)
        chat_id: Optional[int] = Field(None, description="אם לא — יילקח מ־TELEGRAM_TEST_CHAT_ID")
        text: str = Field(..., min_length=1, max_length=4096)
        parse_mode: Optional[str] = Field(None, description="HTML / MarkdownV2 (אם לא נשלח — יילקח מה-ENV אם קיים)")
        disable_preview: bool = Field(True, description="השבתת תצוגה מקדימה")
else:
    class SendRequest(BaseModel):
        class Config:
            extra = "ignore"
            allow_population_by_field_name = True
        chat_id: Optional[int] = Field(None, description="אם לא — יילקח מ־TELEGRAM_TEST_CHAT_ID")
        text: str = Field(..., min_length=1, max_length=4096)
        parse_mode: Optional[str] = Field(None, description="HTML / MarkdownV2 (אם לא נשלח — יילקח מה-ENV אם קיים)")
        disable_preview: bool = Field(True, description="השבתת תצוגה מקדימה")


# ===================== Helpers =====================
def _compose_status_json() -> Dict[str, Any]:
    ws = _ws_get_counters()
    ex = _exec_get_counters()

    def _num(v):
        try:
            return float(v)
        except Exception:
            return None

    ttl_alert = int(os.getenv("STATUS_PRICE_TTL_ALERT_SEC", "10"))
    exec_stale = int(os.getenv("EXEC_TICK_STALE_WARN_SEC", "30"))
    timeouts_burst_alert = int(os.getenv("EXEC_TIMEOUT_BURST_ALERT", "3"))

    ws_state = "OK" if int(ws.get("ws_up") or 0) == 1 and (ws.get("last_event_age_sec") or 0) <= ttl_alert else "WARN"
    ex_state = "OK"
    age = ex.get("last_tick_age_sec")
    if isinstance(age, (int, float)) and age is not None and age > exec_stale:
        ex_state = "WARN"
    if int(ex.get("timeouts_burst") or 0) >= timeouts_burst_alert:
        ex_state = "WARN"

    combined = "PAUSE" if ws_state == "WARN" and (ws.get("last_event_age_sec") or 0) > ttl_alert * 3 else ("WARN" if ("WARN" in (ws_state, ex_state)) else "OK")

    return {
        "ok": True,
        "state": combined,
        "ws": {
            "ws_up": int(ws.get("ws_up") or 0),
            "reconnects": int(ws.get("reconnects") or 0),
            "ewma_latency_ms": _num(ws.get("ewma_latency_ms")),
            "last_event_age_sec": _num(ws.get("last_event_age_sec")),
        },
        "executor": {
            "tick_ewma_ms": _num(ex.get("tick_ewma_ms")),
            "tick_p95_ms": _num(ex.get("tick_p95_ms")),
            "tick_p99_ms": _num(ex.get("tick_p99_ms")),
            "last_tick_age_sec": _num(ex.get("last_tick_age_sec")),
            "timeouts_burst": int(ex.get("timeouts_burst") or 0),
            "no_trade_streak": int(ex.get("no_trade_streak") or 0),
            "current_interval": int(ex.get("current_interval") or 0),
        },
        "reasons": ["healthy"] if combined == "OK" else ["stale_ws" if ws_state != "OK" else "executor_warn"],
    }


def _get_default_chat_id() -> Optional[int]:
    return int(DEFAULT_CHAT) if DEFAULT_CHAT.isdigit() else None


def _validate_webhook_secret(request: Request) -> None:
    """
    Enforce Telegram secret token אם מוגדר (אבטחה אופציונלית).
    """
    if WEBHOOK_SECRET:
        header = request.headers.get("x-telegram-bot-api-secret-token", "")
        if not header or header != WEBHOOK_SECRET:
            # לא חושפים פרטים
            raise HTTPException(status_code=401, detail="Unauthorized")


def _extract_action_ticket_from_update(update: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    תומך בשני פורמטים:
    1) עדכון טלגרם רגיל עם callback_query.data (JSON או 'approve|{json}')
    2) JSON ישיר: {"action":"approve|reject","ticket":{...}}
    מחזיר {"action": "...", "ticket": {...}} או None.
    """
    # פורמט ישיר
    if "action" in update and "ticket" in update:
        try:
            action = str(update.get("action", "")).lower().strip()
            if action in ("approve", "reject") and isinstance(update["ticket"], dict):
                return {"action": action, "ticket": update["ticket"]}
        except Exception:
            pass

    # פורמט טלגרם
    cb = update.get("callback_query") or {}
    data = cb.get("data")
    if isinstance(data, str) and data:
        # JSON ב-data
        try:
            obj = json.loads(data)
            if isinstance(obj, dict) and "action" in obj and "ticket" in obj:
                action = str(obj.get("action", "")).lower().strip()
                if action in ("approve", "reject") and isinstance(obj["ticket"], dict):
                    return {"action": action, "ticket": obj["ticket"]}
        except Exception:
            # fallback: "approve|{json}"
            if data.startswith("approve|") or data.startswith("reject|"):
                try:
                    action, js = data.split("|", 1)
                    action = action.strip().lower()
                    obj = json.loads(js)
                    if isinstance(obj, dict):
                        return {"action": action, "ticket": obj}
                except Exception:
                    pass
            # מילה בלבד
            if data in ("approve", "reject"):
                return {"action": data, "ticket": {}}

    return None


# ===================== Endpoints =====================
@router.get("/health")
async def health() -> Dict[str, Any]:
    if not BOT_TOKEN:
        return {"ok": False, "error": "BOT_TOKEN missing"}
    try:
        async with httpx.AsyncClient(timeout=8.0) as cli:
            me = await cli.get(f"{API_BASE}/getMe")
            wh = await cli.get(f"{API_BASE}/getWebhookInfo")
        me_json = me.json() if "application/json" in me.headers.get("content-type", "") else {}
        wh_json = wh.json() if "application/json" in wh.headers.get("content-type", "") else {}
        return {"ok": True, "bot": me_json.get("result", {}), "webhook": wh_json.get("result", {})}
    except Exception as e:
        logger.warning("telegram/health failed: %s", e)
        return {"ok": False, "error": str(e)}


@router.get("/test-ping")
async def test_ping(chat_id: Optional[int] = Query(None)) -> Dict[str, Any]:
    if not BOT_TOKEN:
        raise HTTPException(500, "BOT_TOKEN missing")
    cid = chat_id or _get_default_chat_id()
    if not cid:
        raise HTTPException(400, "chat_id required (or set TELEGRAM_TEST_CHAT_ID)")
    payload: Dict[str, Any] = {
        "chat_id": cid,
        "text": "pong ✅ (test-ping)",
        "disable_web_page_preview": True,
    }
    if PM_ENV:
        payload["parse_mode"] = PM_ENV
    try:
        async with httpx.AsyncClient(timeout=8.0) as cli:
            r = await cli.post(f"{API_BASE}/sendMessage", json=payload)
        j = r.json() if "application/json" in r.headers.get("content-type", "") else {"ok": False, "raw": r.text}
        return {"ok": bool(j.get("ok")), "result": j}
    except Exception as e:
        logger.error("telegram/test-ping failed: %s", e)
        raise HTTPException(502, str(e))


@router.post("/send")
async def send(req: SendRequest) -> Dict[str, Any]:
    if not BOT_TOKEN:
        raise HTTPException(500, "BOT_TOKEN missing")
    cid = req.chat_id or _get_default_chat_id()
    if not cid:
        raise HTTPException(400, "chat_id required (or set TELEGRAM_TEST_CHAT_ID)")

    payload: Dict[str, Any] = {
        "chat_id": cid,
        "text": req.text,
        "disable_web_page_preview": bool(req.disable_preview),
    }
    pm_effective = req.parse_mode if req.parse_mode is not None else PM_ENV
    if pm_effective:
        payload["parse_mode"] = pm_effective

    try:
        async with httpx.AsyncClient(timeout=8.0) as cli:
            r = await cli.post(f"{API_BASE}/sendMessage", json=payload)
        j = r.json() if "application/json" in r.headers.get("content-type", "") else {"ok": False, "raw": r.text}
        return {"ok": bool(j.get("ok")), "result": j}
    except Exception as e:
        logger.error("telegram/send failed: %s", e)
        raise HTTPException(502, str(e))


@router.get("/set-webhook")
async def set_webhook() -> Dict[str, Any]:
    if not BOT_TOKEN:
        raise HTTPException(500, "BOT_TOKEN missing")
    if not PUBLIC_HOST:
        raise HTTPException(500, "PUBLIC_HOST missing")
    url = f"{PUBLIC_HOST.rstrip('/')}/telegram/webhook"
    body = {
        "url": url,
        "secret_token": WEBHOOK_SECRET,
        "drop_pending_updates": True,
        "max_connections": 40,
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as cli:
            r = await cli.post(f"{API_BASE}/setWebhook", json=body)
        j = r.json() if "application/json" in r.headers.get("content-type", "") else {"ok": False, "raw": r.text}
        return {"ok": bool(j.get("ok")), "telegram_response": j, "requested_url": url}
    except Exception as e:
        logger.error("telegram/set-webhook failed: %s", e)
        raise HTTPException(502, str(e))


@router.get("/status")
async def rest_status() -> Dict[str, Any]:
    return _compose_status_json()


@router.post("/webhook")
async def telegram_webhook(request: Request) -> Dict[str, Any]:
    """
    Webhook מאוחד:
    - מאמת כותרת סודית אם TELEGRAM_WEBHOOK_SECRET מוגדר.
    - מקבל עדכון טלגרם (callback_query.data) או JSON ישיר {"action","ticket"}.
    - על "approve": קורא execute_trade_live(...) עם שדות מינימליים.
    """
    _validate_webhook_secret(request)

    try:
        payload: Dict[str, Any] = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    parsed = _extract_action_ticket_from_update(payload)
    if not parsed:
        # לא חלק מתהליך אישור; מחזירים ack כדי למנוע retries
        return {"ok": True, "noop": True}

    action = parsed["action"]
    ticket = parsed.get("ticket") or {}

    if action == "reject":
        return {"ok": True, "status": "rejected"}

    # APPROVE path
    symbol = str(ticket.get("symbol", "")).upper()
    side = str(ticket.get("side", "")).upper()
    if not symbol or side not in ("LONG", "SHORT"):
        raise HTTPException(status_code=400, detail="invalid ticket (symbol/side)")

    leverage = int(ticket.get("leverage", 10))
    budget = float(ticket.get("budget", 50.0))
    entry = float(ticket.get("entry", 0.0)) or None
    sl = float(ticket.get("sl", 0.0)) or None
    tp1 = float(ticket.get("tp1", 0.0)) or None
    tp2 = float(ticket.get("tp2", 0.0)) or None

    try:
        res = await execute_trade_live(
            symbol=symbol,
            side=side,
            leverage=leverage,
            budget=budget,
            entry=entry,
            sl=sl,
            tp1=tp1,
            tp2=tp2,
            reduce_only=False,
            dry_run=os.getenv("DRY_RUN", "0").lower() in ("1", "true", "yes", "on"),
        )
    except Exception as e:
        logger.exception("execute_trade_live failed")
        raise HTTPException(status_code=500, detail=f"trade failed: {e}")

    return {"ok": True, "status": "executed", "result": res}


























