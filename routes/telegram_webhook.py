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
# תואם גם לפריסה שבה ConfirmStore יושב ב-auto_executor ולא ב-trade_executor
try:
    from utils.auto_executor import ConfirmStore  # חדש
except Exception:
    from utils.trade_executor import ConfirmStore  # תאימות ישנה

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
           










