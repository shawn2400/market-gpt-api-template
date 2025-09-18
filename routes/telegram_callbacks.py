# routes/telegram_callbacks.py
from __future__ import annotations
import os, logging
from typing import Any, Dict, Optional
from fastapi import APIRouter, Request, HTTPException, Header
from fastapi.responses import JSONResponse
import httpx

# ConfirmStore אמור לנהל כרטיסי אישור (pending/approved/rejected) ולהפעיל את ה־executor בעת approve/reject
from utils.trade_executor import ConfirmStore

logger = logging.getLogger("algogpt.telegram.callbacks")
router = APIRouter(prefix="/telegram", tags=["Telegram"])

TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()

ADMIN_ONLY = os.getenv("TELEGRAM_ADMIN_ONLY", "1").lower() in ("1","true","yes","on")
ADMIN_IDS  = {s.strip() for s in (os.getenv("TELEGRAM_ADMIN_IDS","") or "").split(",") if s.strip()}

def _is_admin(uid: int) -> bool:
    if not ADMIN_ONLY:
        return True
    return str(uid) in ADMIN_IDS

# Optional Redis-backed dedup for callback_query ids (防 double-click/dup delivery)
REDIS_URL = os.getenv("REDIS_URL", "").strip()
try:
    import redis  # type: ignore
    _r_cbq = redis.Redis.from_url(REDIS_URL, decode_responses=True) if REDIS_URL else None
except Exception:
    _r_cbq = None
_seen_cbq_mem: set[str] = set()

def _cbq_seen(cbq_id: str, ttl: int = 30) -> bool:
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
    if not TG_TOKEN:
        return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/editMessageReplyMarkup"
    try:
        async with httpx.AsyncClient(timeout=8.0) as cli:
            await cli.post(url, json={"chat_id": chat_id, "message_id": message_id, "reply_markup": {"inline_keyboard": []}})
    except Exception as e:
        logger.warning(f"[tg] editMessageReplyMarkup failed: {e}")

async def _maybe_mark_ticket_approved(rec: Dict[str, Any]) -> None:
    """
    אופציונלי: אם יש לנו trade_id נשגר עדכון ל־/alerts/trades/update (אם קיים ב־ENV).
    זה לא מחליף את ConfirmStore.approve() — רק מסנכרן ל־Alerts Router במקרה שצריך.
    """
    try:
        trade_id = str(rec.get("trade_id") or "")  # עשוי לא להיות
        url = os.getenv("ALERTS_UPDATE_URL", "").strip()
        tok = os.getenv("API_BEARER_TOKEN", os.getenv("PRIMARY_API_TOKEN", "")).strip()
        if trade_id and url and tok:
            headers = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}
            payload = {"trade_id": trade_id, "updates": {"approved": True}}
            async with httpx.AsyncClient(timeout=8.0) as cli:
                await cli.post(url, headers=headers, json=payload)
    except Exception as e:
        logger.debug({"event":"alerts.update.skip_or_fail","err":str(e)})

async def _maybe_mark_ticket_rejected(rec: Dict[str, Any]) -> None:
    try:
        trade_id = str(rec.get("trade_id") or "")
        url = os.getenv("ALERTS_UPDATE_URL", "").strip()
        tok = os.getenv("API_BEARER_TOKEN", os.getenv("PRIMARY_API_TOKEN", "")).strip()
        if trade_id and url and tok:
            headers = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}
            payload = {"trade_id": trade_id, "updates": {"approved": False, "rejected": True}}
            async with httpx.AsyncClient(timeout=8.0) as cli:
                await cli.post(url, headers=headers, json=payload)
    except Exception as e:
        logger.debug({"event":"alerts.update.skip_or_fail","err":str(e)})

@router.post("/callback")
async def callback_handler(
    req: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None)
):
    # Secret guard (mirrors /webhook). טלגרם מוסיף header זה אוטומטית אם הוגדר secret_token
    if WEBHOOK_SECRET and (not x_telegram_bot_api_secret_token or x_telegram_bot_api_secret_token.strip() != WEBHOOK_SECRET):
        raise HTTPException(status_code=401, detail="Invalid telegram secret")

    try:
        update = await req.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Bad payload")

    cb = update.get("callback_query")
    if not cb:
        # לא callback — בסדר, מתעלמים בשקט (ייתכן שזה message רגיל)
        return {"ok": True}

    cb_id = cb.get("id") or ""
    if _cbq_seen(cb_id):
        return {"ok": True}  # דלג על כפולים

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

    try:
        _, action, cid = data.split(":", 2)
    except ValueError:
        await _tg_answer_callback(cb_id, "פורמט לא תקין")
        return {"ok": True}

    rec: Optional[Dict[str, Any]] = ConfirmStore.get(cid)
    if not rec or rec.get("status") != "pending":
        if chat_id and message_id:
            await _disable_kb(chat_id, message_id)
        await _tg_answer_callback(cb_id, "פג תוקף/כבר טופל")
        return {"ok": True}

    try:
        if action == "APPROVE":
            ConfirmStore.approve(cid, approver=str(uid))  # כאן אמור להפעיל את הביצוע החי
            await _maybe_mark_ticket_approved(rec)
            await _tg_answer_callback(cb_id, "אושר ✅")
            if chat_id and message_id:
                await _disable_kb(chat_id, message_id)
            return JSONResponse(content={"ok": True})

        if action == "REJECT":
            ConfirmStore.reject(cid, approver=str(uid))
            await _maybe_mark_ticket_rejected(rec)
            await _tg_answer_callback(cb_id, "בוטל ❌")
            if chat_id and message_id:
                await _disable_kb(chat_id, message_id)
            return JSONResponse(content={"ok": True})

        await _tg_answer_callback(cb_id, "פעולה לא מזוהה")
        return {"ok": True}

    except Exception as e:
        logger.exception({"event":"cbq.handle.error","error":str(e)})
        await _tg_answer_callback(cb_id, "שגיאה פנימית")
        return JSONResponse(status_code=500, content={"ok": False, "error": "internal"})




