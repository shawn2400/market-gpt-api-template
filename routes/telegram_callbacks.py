# routes/telegram_callbacks.py
from __future__ import annotations

"""
Telegram callback router:
- בודק secret header
- מממש כפתורי אישור/דחייה (inline keyboard)
- מוודא idempotency מול Redis (אם מוגדר) כדי למנוע דאבל קליק
- מכבה את המקלדת אחרי פעולה
"""

import os
import logging
import time
import hmac
import hashlib
import json
from typing import Any, Dict

from fastapi import APIRouter, Request, HTTPException, Header
from fastapi.responses import JSONResponse
import httpx

logger = logging.getLogger("algogpt.telegram.callbacks")
router = APIRouter(prefix="/telegram", tags=["Telegram"])

# --- config / env
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()

ADMIN_ONLY = os.getenv("TELEGRAM_ADMIN_ONLY", "1").lower() in ("1", "true", "yes", "on")
ADMIN_IDS = {
    s.strip()
    for s in (os.getenv("TELEGRAM_ADMIN_IDS", "") or "").split(",")
    if s.strip()
}
def _is_admin(uid: int) -> bool:
    if not ADMIN_ONLY:
        return True
    return str(uid) in ADMIN_IDS

# --- ConfirmStore (fallback-aware)
# קודם מנסים מהמודול הייעודי approvals; אם לא קיים — נופלים אל trade_executor
try:
    from utils.approvals import ConfirmStore  # type: ignore
except Exception:
    try:
        from utils.trade_executor import ConfirmStore  # type: ignore
    except Exception:
        class ConfirmStore:  # type: ignore
            @staticmethod
            def get(_cid: str) -> Dict[str, Any] | None:
                return None
            @staticmethod
            def approve(_cid: str, approver: str | None = None) -> Dict[str, Any]:
                return {"ok": False, "error": "ConfirmStore missing"}
            @staticmethod
            def reject(_cid: str, approver: str | None = None) -> Dict[str, Any]:
                return {"ok": False, "error": "ConfirmStore missing"}
            @staticmethod
            async def run(_cid: str) -> Dict[str, Any]:
                return {"ok": False, "error": "executor missing"}

# --- Optional Redis-backed dedup for callback_query ids
REDIS_URL = os.getenv("REDIS_URL", "").strip()
try:
    import redis  # type: ignore
    _r_cbq = redis.Redis.from_url(REDIS_URL, decode_responses=True) if REDIS_URL else None
except Exception:
    _r_cbq = None

_seen_cbq_mem: set[str] = set()

def _cbq_seen(cbq_id: str, ttl: int = 30) -> bool:
    """Return True if this callback id was already seen (dup)."""
    if not cbq_id:
        return False
    if _r_cbq:
        try:
            ok = _r_cbq.set(f"cbq:{cbq_id}", "1", nx=True, ex=ttl)
            return not bool(ok)
        except Exception:
            pass
    if cbq_id in _seen_cbq_mem:
        return True
    _seen_cbq_mem.add(cbq_id)
    if len(_seen_cbq_mem) > 5000:
        _seen_cbq_mem.clear()
    return False

async def _tg_answer_callback(cbq_id: str, text: str = "") -> None:
    if not (TG_TOKEN and cbq_id):
        return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/answerCallbackQuery"
    try:
        async with httpx.AsyncClient(timeout=8.0) as cli:
            await cli.post(url, json={"callback_query_id": cbq_id, "text": text, "show_alert": False})
    except Exception as e:
        logger.warning(f"[tg] answerCallbackQuery failed: {e}")

async def _disable_kb(chat_id: int, message_id: int) -> None:
    """Remove inline keyboard after action."""
    if not TG_TOKEN:
        return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/editMessageReplyMarkup"
    try:
        async with httpx.AsyncClient(timeout=8.0) as cli:
            await cli.post(url, json={
                "chat_id": chat_id,
                "message_id": message_id,
                "reply_markup": {"inline_keyboard": []}
            })
    except Exception as e:
        logger.warning(f"[tg] editMessageReplyMarkup failed: {e}")

# --- Signed approve POST helper ---
PUBLIC_HOST = os.getenv("PUBLIC_HOST","").rstrip("/")
OPS_SIGN_SECRET = (os.getenv("OPS_SIGN_SECRET","") or os.getenv("WEBHOOK_HMAC_SECRET","")).strip()
API_TOKEN = (os.getenv("API_TOKEN","") or os.getenv("API_BEARER_TOKEN","")).strip()

async def _post_signed_approval(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    מקבל payload {'symbol','side','qty' או 'budget','price','lev','position_side', ...}
    ושולח POST חתום ל-/ops/approve/signed. מחזיר תשובת השרת.
    """
    if not PUBLIC_HOST:
        return {"ok": False, "error": "PUBLIC_HOST not set"}
    if not OPS_SIGN_SECRET:
        return {"ok": False, "error": "OPS_SIGN_SECRET not set"}

    body = dict(payload)
    body.setdefault("action", "approve")
    body.setdefault("ticket_id", f"tg_{int(time.time())}")

    raw = json.dumps(body, ensure_ascii=False, separators=(",",":")).encode("utf-8")
    sig = hmac.new(OPS_SIGN_SECRET.encode("utf-8"), raw, hashlib.sha256).hexdigest()

    url = f"{PUBLIC_HOST}/ops/approve/signed"
    headers = {"X-Signature": sig, "Content-Type": "application/json"}
    # שמרתי התאמה לגרסאות ישנות: אם יש טוקן, שולחים בכותרת X-API-Key; אם השרת דורש Bearer — בצד השרת יש תמיכה.
    if API_TOKEN:
        headers["X-API-Key"] = API_TOKEN

    try:
        async with httpx.AsyncClient(timeout=15.0) as cli:
            r = await cli.post(url, content=raw, headers=headers)
            data = r.json() if r.headers.get("content-type","").startswith("application/json") else {"text": r.text}
            return {"ok": r.status_code < 400, "status": r.status_code, "response": data}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@router.post("/callback")
async def callback_handler(
    req: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None)
):
    # Security: match secret token (Telegram will send this header when webhook set with secret_token)
    if WEBHOOK_SECRET and (not x_telegram_bot_api_secret_token or x_telegram_bot_api_secret_token.strip() != WEBHOOK_SECRET):
        raise HTTPException(status_code=401, detail="Invalid telegram secret")

    try:
        update = await req.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Bad payload")

    cb = update.get("callback_query")
    if not cb:
        return {"ok": True}

    cb_id = cb.get("id") or ""
    if _cbq_seen(cb_id):
        return {"ok": True}

    from_user = cb.get("from") or {}
    uid = int(from_user.get("id") or 0)
    msg = cb.get("message") or {}
    chat_id = int((msg.get("chat") or {}).get("id") or 0)
    message_id = int(msg.get("message_id") or 0)
    data = str(cb.get("data") or "")

    if not _is_admin(uid):
        await _tg_answer_callback(cb_id, "⛔️ אין הרשאה")
        return {"ok": True}

    if not data.startswith("CONFIRM:"):
        await _tg_answer_callback(cb_id, "לא נתמך")
        return {"ok": True}

    # Import verify_callback_data to properly validate signed callbacks
    try:
        from utils.telegram_notifier import verify_callback_data
        parsed = verify_callback_data(data)
        action = parsed.get("action", "")
        cid = parsed.get("trade_id", "")
    except ValueError as e:
        error_msg = str(e)
        if error_msg == "unsigned_callback":
            await _tg_answer_callback(cb_id, "⚠️ חתימה חסרה")
        elif error_msg == "bad_sig":
            await _tg_answer_callback(cb_id, "⚠️ חתימה לא תקינה")
        elif error_msg == "expired":
            await _tg_answer_callback(cb_id, "⏰ פג תוקף")
        else:
            await _tg_answer_callback(cb_id, f"שגיאה: {error_msg}")
        logger.warning(f"[callback] verify failed: {error_msg} | data={data}")
        return {"ok": True}
    except Exception as e:
        await _tg_answer_callback(cb_id, "פורמט לא תקין")
        logger.error(f"[callback] parse error: {e}")
        return {"ok": True}

    rec = ConfirmStore.get(cid)
    if not rec or rec.get("status") != "pending":
        if chat_id and message_id:
            await _disable_kb(chat_id, message_id)
        await _tg_answer_callback(cb_id, "פג תוקף/כבר טופל")
        return {"ok": True}

    if action == "APPROVE":
        ConfirmStore.approve(cid, approver=str(uid))
        # שליחת ביצוע חתום + פידבק קצר
        payload = (rec.get("payload") or {}).copy()
        payload.setdefault("position_side", "BOTH")
        result = await _post_signed_approval(payload)
        status_txt = "✅ בוצע" if result.get("ok") else "⚠️ כשל בביצוע"
        await _tg_answer_callback(cb_id, status_txt)
        if chat_id and message_id:
            await _disable_kb(chat_id, message_id)
        return JSONResponse(content={"ok": True, "posted": result})

    if action == "REJECT":
        ConfirmStore.reject(cid, approver=str(uid))
        await _tg_answer_callback(cb_id, "בוטל ❌")
        if chat_id and message_id:
            await _disable_kb(chat_id, message_id)
        return JSONResponse(content={"ok": True})

    await _tg_answer_callback(cb_id, "פעולה לא מזוהה")
    return {"ok": True}



