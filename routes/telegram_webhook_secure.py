# routes/telegram_webhook_secure.py
from __future__ import annotations
import os
import time
import ipaddress
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request, HTTPException, Header
from fastapi.responses import JSONResponse

try:
    import redis  # type: ignore
except Exception:
    redis = None

# Optional: שימוש באישור טריידים דרך כפתורי אינליין
try:
    from utils.trade_executor import ConfirmStore
except Exception:
    class ConfirmStore:  # fallback no-op
        @staticmethod
        def approve(cid: str, approver: str | None = None): ...
        @staticmethod
        def reject(cid: str, approver: str | None = None): ...
        @staticmethod
        def flush(): ...

router = APIRouter(tags=["Telegram"])

log = logging.getLogger("algogpt.telegram.secure")

# ------------------------------------------------------------------------------
# ENV
# ------------------------------------------------------------------------------
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()

# Allowlist של טווחי ה-IP של טלגרם (ברירת מחדל לפי התיעוד)
# אפשר לעדכן דרך TELEGRAM_IP_ALLOWLIST="149.154.160.0/20,91.108.4.0/22"
DEFAULT_TG_CIDRS = ["149.154.160.0/20", "91.108.4.0/22"]
CIDRS = [c.strip() for c in os.getenv("TELEGRAM_IP_ALLOWLIST", ",".join(DEFAULT_TG_CIDRS)).split(",") if c.strip()]

# אידמפוטנטיות (שימוש ב-Redis אם מוגדר, אחרת in-memory)
USE_REDIS_IDEM = os.getenv("USE_REDIS_IDEM", "1").lower() in ("1", "true", "yes", "on")
REDIS_URL = os.getenv("REDIS_URL", "").strip()
IDEMP_TTL_SEC = int(os.getenv("TELEGRAM_IDEMP_TTL_SEC", "900"))  # 15 דקות

# Rate limit קליל (ברירת מחדל: 90 לדקה burst 45)
TG_RPM = int(os.getenv("TELEGRAM_RPM", "90"))
TG_BURST = int(os.getenv("TELEGRAM_BURST", "45"))

# ------------------------------------------------------------------------------
# Redis / In-memory stores
# ------------------------------------------------------------------------------
_rcli = None
if USE_REDIS_IDEM and REDIS_URL and redis:
    try:
        _rcli = redis.from_url(REDIS_URL, decode_responses=True)
    except Exception as e:
        log.warning("Redis connect failed: %s", e)
        _rcli = None

# אידמפוטנטיות fallback (in-memory)
_seen_updates: Dict[str, float] = {}

# Rate-limit (per minute, in-memory; עדיף Redis אבל מספיק ל־webhook)
_rl_window: Dict[str, List[float]] = {}  # key -> list of ts (seconds)

# ------------------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------------------
def _client_ip(request: Request) -> str:
    # ברנדר/פרוקסי כדאי לבדוק X-Forwarded-For
    xff = request.headers.get("x-forwarded-for") or request.headers.get("X-Forwarded-For")
    if xff:
        # לוקחים את הראשון (הקרוב ללקוח)
        return xff.split(",")[0].strip()
    return (request.client.host if request.client else "0.0.0.0")

def _ip_allowed(ip_str: str, cidrs: List[str]) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except Exception:
        return False
    for c in cidrs:
        try:
            if ip in ipaddress.ip_network(c, strict=False):
                return True
        except Exception:
            continue
    return False

def _rate_limited(key: str) -> bool:
    now = time.time()
    win = _rl_window.setdefault(key, [])
    # מנקים חלון של 60 שניות
    cutoff = now - 60.0
    while win and win[0] < cutoff:
        win.pop(0)
    # בדיקת burst
    if len(win) >= TG_BURST:
        return True
    # בדיקת RPM
    if len(win) >= TG_RPM:
        return True
    win.append(now)
    return False

def _idem_key(update: Dict[str, Any]) -> Optional[str]:
    # לפי update_id אם קיים; אחרת hash של כל הגוף (לא כבד כאן)
    if "update_id" in update:
        return f"tg_update:{update['update_id']}"
    try:
        import orjson as _json  # type: ignore
    except Exception:
        import json as _json
    return "tg_body:" + str(abs(hash(_json.dumps(update))))

def _idem_seen(key: str) -> bool:
    if _rcli:
        try:
            # SETNX + EXPIRE
            with _rcli.pipeline() as p:
                p.setnx(key, int(time.time()))
                p.expire(key, IDEMP_TTL_SEC)
                res = p.execute()
            return not bool(res[0])  # True if already existed
        except Exception as e:
            log.warning("Redis idempotency failed: %s", e)
    # in-memory
    now = time.time()
    # cleanup
    for k, ts in list(_seen_updates.items()):
        if now - ts > IDEMP_TTL_SEC:
            _seen_updates.pop(k, None)
    if key in _seen_updates:
        return True
    _seen_updates[key] = now
    return False

def _require_secret(header_token: Optional[str]):
    if not WEBHOOK_SECRET:
        # אם אין secret בקונפי—מאפשרים רק אם סביבת dev
        if os.getenv("ENV", "prod") != "dev":
            raise HTTPException(401, "Webhook secret not configured")
        return
    if not header_token or header_token.strip() != WEBHOOK_SECRET:
        raise HTTPException(401, "Invalid telegram secret")

# ------------------------------------------------------------------------------
# Public ping (לבדיקה ידנית) — לא מציגים ב-OpenAPI
# ------------------------------------------------------------------------------
@router.get("/telegram/ping", include_in_schema=False)
async def ping():
    return {"ok": True, "src": "telegram", "ts": int(time.time() * 1000)}

# ------------------------------------------------------------------------------
# Webhook מאובטח
# ------------------------------------------------------------------------------
@router.post("/telegram/webhook", include_in_schema=False)
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: Optional[str] = Header(default=None),
):
    # 1) אימות Secret header של Telegram (dual #1)
    _require_secret(x_telegram_bot_api_secret_token)

    # 2) Allowlist ל־IP (dual #2)
    ip = _client_ip(request)
    if CIDRS and not _ip_allowed(ip, CIDRS):
        log.warning("Telegram webhook from non-allowed IP: %s", ip)
        raise HTTPException(401, "IP not allowed")

    # 3) Rate-limit בסיסי כדי לא להיחנק במקרה של הצפות
    if _rate_limited("tg_webhook"):
        return JSONResponse(status_code=429, content={"ok": False, "error": "rate_limited"})

    # 4) פרסינג JSON
    try:
        update = await request.json()
    except Exception:
        raise HTTPException(400, "invalid JSON")

    # 5) אידמפוטנטיות
    ikey = _idem_key(update)
    if ikey and _idem_seen(ikey):
        return {"ok": True, "dedup": True}

    # 6) לוגיקה בסיסית (כפתורי אינליין + /ping)
    # Inline buttons: "CONFIRM:APPROVE:<cid>" / "CONFIRM:REJECT:<cid>"
    cb = update.get("callback_query")
    if cb:
        data = str(cb.get("data", ""))
        chat = (cb.get("message", {}).get("chat", {}) or cb.get("from", {}))
        chat_id = int(chat.get("id", 0))
        parts = data.split(":", 2)
        if len(parts) == 3 and parts[0] == "CONFIRM":
            action, cid = parts[1], parts[2]
            approver = str(cb.get("from", {}).get("username") or chat_id)
            if action == "APPROVE":
                ConfirmStore.approve(cid, approver=approver)
            else:
                ConfirmStore.reject(cid, approver=approver)
        return {"ok": True}

    msg = update.get("message")
    if msg and str(msg.get("text", "")).strip() == "/ping":
        # לא עונים כאן לטלגרם כדי לשמור latency; ההודעה לבוט נעשית בצד אחר
        return {"ok": True, "pong": True}

    return {"ok": True}
