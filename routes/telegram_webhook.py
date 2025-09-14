# routes/telegram_webhook.py
from __future__ import annotations
import os, logging, time
from typing import Any, Dict, Optional, List
from fastapi import APIRouter, Request, HTTPException
import httpx

logger = logging.getLogger("algogpt.telegram.webhook")

# שים לב: קובץ זה מוסיף /telegram/commands בלבד (לא מתנגש עם /telegram/webhook הקיים)
router = APIRouter(prefix="/telegram", tags=["Telegram"])

TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
ADMIN_ONLY = str(os.getenv("TELEGRAM_ADMIN_ONLY", "1")).lower() in ("1","true","yes","on")
ADMIN_IDS = {s.strip() for s in (os.getenv("TELEGRAM_ADMIN_IDS","") or "").split(",") if s.strip()}

def _allowed_user(uid: int) -> bool:
    if not ADMIN_ONLY:
        return True
    return str(uid) in ADMIN_IDS

async def _reply(chat_id: int, text: str, *, html: bool = True) -> None:
    """שליחת תשובה למשתמש בטלגרם (parse_mode=HTML, ללא preview)"""
    if not TG_TOKEN:
        return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML" if html else "Markdown",
        "disable_web_page_preview": True,
    }
    try:
        async with httpx.AsyncClient(timeout=8.0) as cli:
            await cli.post(url, data=payload)
    except Exception as e:
        logger.warning(f"[tg] sendMessage failed: {e}")

# ===== Fallback-safe status sources =====
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
    def set_explain_enabled(v: bool) -> None: pass
    def get_explain_enabled() -> bool: return False

# אופציונלי — רשימת פוזיציות פתוחות
try:
    from utils.binance_client import get_open_positions as _get_open_positions
except Exception:
    def _get_open_positions() -> List[Dict[str, Any]]:
        return []

HELP_TEXT = (
    "🤖 <b>AlgoGPT Bot</b> — Help / עזרה\n\n"
    "• /help — עזרה\n"
    "• /ping — פינג\n"
    "• /status — סטטוס מערכת (WS+Executor)\n"
    "• /positions — פוזיציות פתוחות (תמצית)\n"
    "• /explain_on — הפעלת הסברי טריידים\n"
    "• /explain_off — כיבוי הסברי טריידים\n"
)

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
    extra = len(rows)-len(lines)
    if extra > 0:
        lines.append(f"… ועוד {extra} פריטים")
    return "\n".join(lines)

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
    if isinstance(age, (int,float)) and age is not None and age > int(os.getenv("EXEC_TICK_STALE_WARN_SEC","30")):
        ex_state = "WARN"
    if int(ex.get("timeouts_burst") or 0) >= int(os.getenv("EXEC_TIMEOUT_BURST_ALERT","3")):
        ex_state = "WARN"
    combined = "PAUSE" if ws_state=="WARN" and (ws.get("last_event_age_sec") or 0) > int(os.getenv("STATUS_PRICE_TTL_ALERT_SEC","10"))*3 else ("WARN" if ("WARN" in (ws_state, ex_state)) else "OK")
    lines = [
        f"📊 <b>Status</b> [{combined}]",
        f"WS: up={ws.get('ws_up')} ttl={ws.get('last_event_age_sec')}s ewma={_n(ws.get('ewma_latency_ms'))}ms rc={ws.get('reconnects')}",
        f"EXE: age={ex.get('last_tick_age_sec')}s ewma={_n(ex.get('tick_ewma_ms'))} p95={_n(ex.get('tick_p95_ms'))} tb={ex.get('timeouts_burst')} itv={ex.get('current_interval')}",
    ]
    return "\n".join(lines)

@router.post("/commands")
async def commands(req: Request):
    """נתיב וובהוק לפקודות טלגרם (ללא התנגשות עם /telegram/webhook הישן).
       הגבלות: ADMIN_ONLY + TELEGRAM_ADMIN_IDS.
    """
    if not TG_TOKEN:
        raise HTTPException(status_code=400, detail="Missing TELEGRAM_BOT_TOKEN")
    try:
        update = await req.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Bad payload")

    # תמיכה ב-callback_query קיימת דרך קבצים אחרים במערכת.
    msg = update.get("message") or {}
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    user = msg.get("from") or {}
    uid = int(user.get("id") or 0)
    text = (msg.get("text") or "").strip()

    if not chat_id or not uid:
        return {"ok": True}
    if not _allowed_user(uid):
        await _reply(chat_id, "⛔️ אין לך הרשאה להשתמש בבוט זה.")
        return {"ok": True}

    if not text or text.lower() in ("/start", "/help"):
        await _reply(chat_id, HELP_TEXT)
        return {"ok": True}

    parts = text.split()
    cmd = parts[0].lower()

    if cmd == "/ping":
        await _reply(chat_id, f"pong ✅ {int(time.time())}")
        return {"ok": True}

    if cmd == "/status":
        await _reply(chat_id, _fmt_status())
        return {"ok": True}

    if cmd == "/positions":
        rows = _get_open_positions() or []
        await _reply(chat_id, _fmt_positions(rows))
        return {"ok": True}

    if cmd == "/explain_on":
        set_explain_enabled(True)
        await _reply(chat_id, "🟢 Explain-Trade: ON")
        return {"ok": True}

    if cmd == "/explain_off":
        set_explain_enabled(False)
        await _reply(chat_id, "⚪️ Explain-Trade: OFF")
        return {"ok": True}

    await _reply(chat_id, "❓ פקודה לא מזוהה. /help לתפריט.")
    return {"ok": True}







