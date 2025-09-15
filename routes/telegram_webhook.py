# routes/telegram_webhook.py
from __future__ import annotations
import os, logging, time, re
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Request, HTTPException, Header
import httpx

logger = logging.getLogger("algogpt.telegram.webhook")

router = APIRouter(prefix="/telegram", tags=["Telegram"])

# ─────────── Env / Auth ───────────
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
ADMIN_ONLY = str(os.getenv("TELEGRAM_ADMIN_ONLY", "1")).lower() in ("1","true","yes","on")
ADMIN_IDS = {s.strip() for s in (os.getenv("TELEGRAM_ADMIN_IDS","") or "").split(",") if s.strip()}
PM_ENV: Optional[str] = (os.getenv("TELEGRAM_PARSE_MODE", "").strip() or None)  # None => לא שולחים parse_mode

def _allowed_user(uid: int) -> bool:
    if not ADMIN_ONLY:
        return True
    return str(uid) in ADMIN_IDS

# ─────────── Small helpers ───────────
_TAG_RE = re.compile(r"<[^>]+>")

def _to_plain(text: str) -> str:
    # המרה עדינה לטקסט “נקי” אם אין parse_mode
    return _TAG_RE.sub("", text).replace("&nbsp;", " ").replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")

async def _reply(chat_id: int, text: str, *, html: bool = True) -> None:
    if not TG_TOKEN:
        return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    payload: Dict[str, Any] = {
        "chat_id": chat_id,
        "text": text if (html and PM_ENV) else (_to_plain(text) if html else text),
        "disable_web_page_preview": True,
    }
    if PM_ENV:
        payload["parse_mode"] = PM_ENV
    try:
        async with httpx.AsyncClient(timeout=8.0) as cli:
            await cli.post(url, json=payload)
    except Exception as e:
        logger.warning(f"[tg] sendMessage failed: {e}")

# ─────────── Status Providers (fallback-safe) ───────────
try:
    from utils.runtime_counters import ws_get_counters as _ws_get_counters
except Exception:
    def _ws_get_counters() -> Dict[str, Any]:
        return {"ws_up": 0, "reconnects": 0, "ewma_latency_ms": 0.0, "last_event_age_sec": None}

try:
    from utils.runtime_counters import exec_get_counters as _exec_get_counters
except Exception:
    def _exec_get_counters() -> Dict[str, Any]:
        return {
            "tick_ewma_ms": 0.0, "tick_p95_ms": None, "tick_p99_ms": None,
            "last_tick_age_sec": None, "timeouts_burst": 0,
            "no_trade_streak": 0, "current_interval": 0,
        }

try:
    from utils.telegram_notifier import set_explain_enabled, get_explain_enabled
except Exception:
    def set_explain_enabled(v: bool) -> None:  # type: ignore
        pass
    def get_explain_enabled() -> bool:  # type: ignore
        return False

try:
    from utils.binance_client import get_open_positions as _get_open_positions
except Exception:
    def _get_open_positions() -> List[Dict[str, Any]]:
        return []

# ─────────── ConfirmStore & Callback Idempotency ───────────
from utils.trade_executor import ConfirmStore

REDIS_URL = os.getenv("REDIS_URL", "").strip()
try:
    import redis  # type: ignore
    _r_cbq = redis.Redis.from_url(REDIS_URL, decode_responses=True) if REDIS_URL else None
except Exception:
    _r_cbq = None
_seen_cbq_mem: set[str] = set()

def _cbq_seen(cbq_id: str, ttl: int = 30) -> bool:
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

async def _tg_answer_callback(token: str, cbq_id: str, text: str) -> None:
    url = f"https://api.telegram.org/bot{token}/answerCallbackQuery"
    try:
        async with httpx.AsyncClient(timeout=6.0) as cli:
            await cli.post(url, json={"callback_query_id": cbq_id, "text": text, "show_alert": False})
    except Exception as e:
        logger.warning(f"[tg] answerCallbackQuery failed: {e}")

async def _tg_disable_kb(token: str, chat_id: int, message_id: int) -> None:
    url = f"https://api.telegram.org/bot{token}/editMessageReplyMarkup"
    try:
        async with httpx.AsyncClient(timeout=6.0) as cli:
            await cli.post(url, json={
                "chat_id": chat_id,
                "message_id": message_id,
                "reply_markup": {"inline_keyboard": []}
            })
    except Exception as e:
        logger.warning(f"[tg] editMessageReplyMarkup failed: {e}")

# ─────────── UI Strings ───────────
HELP_TEXT_HTML = (
    "🤖 <b>AlgoGPT Bot</b> — Help / עזרה\n\n"
    "• /help — עזרה\n"
    "• /ping — פינג\n"
    "• /status — סטטוס מערכת (WS+Executor)\n"
    "• /positions — פוזיציות פתוחות (תמצית)\n"
    "• /explain_on — הפעלת הסברי טריידים\n"
    "• /explain_off — כיבוי הסברי טריידים\n"
)
HELP_TEXT_PLAIN = _to_plain(HELP_TEXT_HTML)

def _fmt_positions(rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return "אין פוזיציות פתוחות."
    lines = []
    for p in rows[:15]:
        try:
            sym = (p.get("symbol") or "").upper()
            amt = float(p.get("positionAmt") or 0.0)
            entry = float(p.get("entryPrice") or 0.0)
            side = "LONG" if amt > 0 else "SHORT"
            lines.append(f"• <b>{sym}</b> {side} qty={abs(amt):.4f} @ {entry:.4f}")
        except Exception:
            continue
    extra = len(rows) - len(lines)
    if extra > 0:
        lines.append(f"… ועוד {extra} פריטים")
    txt = "\n".join(lines)
    return txt if PM_ENV else _to_plain(txt)

def _fmt_status() -> str:
    ws = _ws_get_counters()
    ex = _exec_get_counters()
    def _n(v):
        try:
            return f"{float(v):.2f}"
        except Exception:
            return str(v)
    ws_state = "OK" if int(ws.get("ws_up") or 0) == 1 and (ws.get("last_event_age_sec") or 0) <= int(os.getenv("STATUS_PRICE_TTL_ALERT_SEC","10")) else "WARN"
    ex_state = "OK"
    age = ex.get("last_tick_age_sec")
    if isinstance(age, (int, float)) and age is not None and age > int(os.getenv("EXEC_TICK_STALE_WARN_SEC","30")):
        ex_state = "WARN"
    if int(ex.get("timeouts_burst") or 0) >= int(os.getenv("EXEC_TIMEOUT_BURST_ALERT","3")):
        ex_state = "WARN"
    combined = "PAUSE" if ws_state == "WARN" and (ws.get("last_event_age_sec") or 0) > int(os.getenv("STATUS_PRICE_TTL_ALERT_SEC","10")) * 3 else ("WARN" if ("WARN" in (ws_state, ex_state)) else "OK")
    lines = [
        f"📊 <b>Status</b> [{combined}]",
        f"WS: up={ws.get('ws_up')} ttl={ws.get('last_event_age_sec')}s ewma={_n(ws.get('ewma_latency_ms'))}ms rc={ws.get('reconnects')}",
        f"EXE: age={ex.get('last_tick_age_sec')}s ewma={_n(ex.get('tick_ewma_ms'))} p95={_n(ex.get('tick_p95_ms'))} tb={ex.get('timeouts_burst')} itv={ex.get('current_interval')}",
    ]
    txt = "\n".join(lines)
    return txt if PM_ENV else _to_plain(txt)

# ─────────── Webhook Endpoint (messages + callbacks) ───────────
@router.post("/commands")
async def commands(
    req: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
):
    if not TG_TOKEN:
        raise HTTPException(status_code=400, detail="Missing TELEGRAM_BOT_TOKEN")

    # הגנת Secret (אופציונלי, תואם /webhook הראשי)
    if WEBHOOK_SECRET and (not x_telegram_bot_api_secret_token or x_telegram_bot_api_secret_token.strip() != WEBHOOK_SECRET):
        raise HTTPException(status_code=401, detail="Invalid telegram secret")

    try:
        update = await req.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Bad payload")

    # --- callback_query: אישור/ביטול טרייד ---
    cbq = update.get("callback_query")
    if cbq:
        cbq_id = cbq.get("id") or ""
        if _cbq_seen(cbq_id):
            return {"ok": True}

        from_user = cbq.get("from") or {}
        uid = int(from_user.get("id") or 0)
        msg = cbq.get("message") or {}
        chat = msg.get("chat") or {}
        chat_id = chat.get("id")
        message_id = msg.get("message_id")
        data = (cbq.get("data") or "").strip()

        if not chat_id or not message_id:
            return {"ok": True}
        if not _allowed_user(uid):
            await _tg_answer_callback(TG_TOKEN, cbq_id, "⛔️ אין הרשאה")
            return {"ok": True}

        parts = data.split(":", 2)
        if len(parts) != 3:
            await _tg_answer_callback(TG_TOKEN, cbq_id, "פורמט לא תקין")
            return {"ok": True}
        kind, action, cid = parts
        if kind != "CONFIRM":
            await _tg_answer_callback(TG_TOKEN, cbq_id, "לא נתמך")
            return {"ok": True}

        rec = ConfirmStore.get(cid)
        if not rec or rec.get("status") != "pending":
            await _tg_disable_kb(TG_TOKEN, chat_id, message_id)
            await _tg_answer_callback(TG_TOKEN, cbq_id, "פג תוקף/כבר טופל")
            return {"ok": True}

        if action == "APPROVE":
            ConfirmStore.approve(cid, approver=str(uid))
            await _tg_answer_callback(TG_TOKEN, cbq_id, "אושר ✅")
            await _tg_disable_kb(TG_TOKEN, chat_id, message_id)
            return {"ok": True}

        if action == "REJECT":
            ConfirmStore.reject(cid, approver=str(uid))
            await _tg_answer_callback(TG_TOKEN, cbq_id, "בוטל ❌")
            await _tg_disable_kb(TG_TOKEN, chat_id, message_id)
            return {"ok": True}

        await _tg_answer_callback(TG_TOKEN, cbq_id, "פעולה לא מזוהה")
        return {"ok": True}

    # --- text messages (/help, /status, ...) ---
    msg = update.get("message") or {}
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    user = msg.get("from") or {}
    uid = int(user.get("id") or 0)
    text = (msg.get("text") or "").strip()

    if not chat_id or not uid:
        return {"ok": True}
    if not _allowed_user(uid):
        await _reply(chat_id, "⛔️ אין לך הרשאה להשתמש בבוט זה.", html=False)
        return {"ok": True}

    if not text or text.lower() in ("/start", "/help"):
        await _reply(chat_id, HELP_TEXT_HTML if PM_ENV else HELP_TEXT_PLAIN, html=bool(PM_ENV))
        return {"ok": True}

    parts = text.split()
    cmd = parts[0].lower()

    if cmd == "/ping":
        await _reply(chat_id, f"pong ✅ {int(time.time())}", html=False)
        return {"ok": True}

    if cmd == "/status":
        await _reply(chat_id, _fmt_status(), html=bool(PM_ENV))
        return {"ok": True}

    if cmd == "/positions":
        rows = _get_open_positions() or []
        await _reply(chat_id, _fmt_positions(rows), html=bool(PM_ENV))
        return {"ok": True}

    if cmd == "/explain_on":
        set_explain_enabled(True)
        await _reply(chat_id, "🟢 Explain-Trade: ON", html=False)
        return {"ok": True}

    if cmd == "/explain_off":
        set_explain_enabled(False)
        await _reply(chat_id, "⚪️ Explain-Trade: OFF", html=False)
        return {"ok": True}

    await _reply(chat_id, "❓ פקודה לא מזוהה. /help לתפריט.", html=False)
    return {"ok": True}

           










