# utils/telegram_notifier.py
from __future__ import annotations
import os, logging, httpx, asyncio
from typing import Dict, Any, Optional
from datetime import datetime

try:
    from zoneinfo import ZoneInfo
    _TZ_IL = ZoneInfo("Asia/Jerusalem")
except Exception:
    _TZ_IL = None

logger = logging.getLogger("algogpt.telegram")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")
ADMIN_CHAT_ID      = os.getenv("ADMIN_CHAT_ID", "")

_http_client: httpx.AsyncClient | None = None
_sent_cache: set[str] = set()   # dedup

def _now_il_str() -> str:
    if _TZ_IL:
        return datetime.now(_TZ_IL).strftime("%d/%m/%Y | %H:%M")
    return datetime.utcnow().strftime("%d/%m/%Y | %H:%M")

async def _ensure_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(timeout=15.0)
    return _http_client

async def _post(text: str, dedup: bool = True):
    chat_id = TELEGRAM_CHAT_ID or ADMIN_CHAT_ID
    if not TELEGRAM_BOT_TOKEN or not chat_id:
        logger.warning("Telegram not configured")
        return

    key = f"{chat_id}:{text.strip()}"
    if dedup and key in _sent_cache:
        return
    _sent_cache.add(key)

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        client = await _ensure_client()
        await client.post(url, json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True
        })
    except Exception as e:
        logger.error(f"Telegram send failed: {e}")

# ====== Notifications ======
async def notify_sl_tp_update(symbol: str, side: str, update_type: str, new_price: float):
    icons = {"breakeven": "✅", "trailing": "⚠️", "tp": "🎯"}
    names = {"breakeven": "SL → BE", "trailing": "Trailing SL", "tp": "Dynamic TP"}
    icon, title = icons.get(update_type, "ℹ️"), names.get(update_type, update_type)
    text = (
        f"{icon} *{title}*\n"
        f"{'🟢' if side.upper()=='LONG' else '🔴'} {symbol.upper()} ({side})\n"
        f"📈 {new_price:.2f} USDT\n"
        f"⏱ {_now_il_str()}"
    )
    await _post(text)

async def notify_info(text: str): await _post(text, dedup=False)
async def notify_error(text: str): await _post(f"⚠️ Error: {text}", dedup=False)
async def notify_heartbeat(): await _post(f"🟢 Heartbeat {_now_il_str()}: AlgoGPT חי ונושם")
async def notify_daily_summary(summary: Dict[str, Any]):
    text = f"📊 Daily Summary {_now_il_str()}\nPnL: {summary['pnl']:.2f} USDT\nTrades: {len(summary['trades'])}"
    await _post(text, dedup=False)
async def notify_trade_review(symbol: str, review: str): 
    await _post(f"✍️ Review {symbol}: {review}", dedup=False)

# ====== Callbacks router (NEW) ======
def _extract_callback(update) -> Dict[str, Any]:
    """
    תומך ב-telegram.Update עם callback_query או message.
    מחלץ action, symbol, side, ומדדים אופציונליים אם קיימים ב-data (JSON/kv).
    """
    action = None; data: Dict[str, Any] = {}
    try:
        if hasattr(update, "callback_query") and update.callback_query and update.callback_query.data:
            raw = update.callback_query.data
            # ניסיון JSON תחילה
            try:
                import json
                data = json.loads(raw)
                action = data.get("action") or data.get("a")
            except Exception:
                # נפוץ: "approve|BTCUSDT|LONG|entry=...,sl=..."
                parts = str(raw).split("|")
                action = parts[0].strip().lower() if parts else None
                if len(parts) > 1: data["symbol"] = parts[1].strip()
                if len(parts) > 2: data["side"] = parts[2].strip()
                for kv in parts[3:]:
                    if "=" in kv:
                        k,v = kv.split("=",1); data[k]=v
        elif hasattr(update, "message") and update.message and update.message.text:
            t = (update.message.text or "").strip()
            # פקודות טקסט פשוטות
            if t.startswith("/approve"): action="approve"
            elif t.startswith("/reject"): action="reject"
            else: action="noop"
            data["text"]=t
    except Exception:
        action = "noop"
    return {"action": (action or "noop").lower(), **data}

async def handle_callback_action(update) -> Dict[str, Any]:
    """
    מחזיר תמיד dict עם המפתחות:
      ok: bool, action: str, approved: bool, symbol/side/entry/sl/leverage/budget_usd אופציונליים.
    """
    try:
        info = _extract_callback(update)
        action = info.get("action","noop").lower()
        symbol = (info.get("symbol") or "").upper() or None
        side = (info.get("side") or "").upper() or None

        approved = action in ("approve","approved","yes","ok","y")
        rejected = action in ("reject","rejected","no","n","deny","denied")

        out: Dict[str, Any] = {"ok": True, "action": action, "approved": approved}
        if symbol: out["symbol"] = symbol
        if side: out["side"] = side

        # המרות אופציונליות
        for k in ("entry","sl","tp","leverage","budget_usd","success_pct"):
            if k in info:
                try:
                    out[k] = float(info[k]) if k not in ("leverage",) else int(float(info[k]))
                except Exception:
                    out[k] = info[k]

        # שלח נוטיפיקציה מנומסת
        if approved and symbol and side:
            await notify_info(f"✅ Approved {symbol} {side} @ {_now_il_str()}")
        elif rejected and symbol and side:
            await notify_info(f"❌ Rejected {symbol} {side} @ {_now_il_str()}")

        return out
    except Exception as e:
        logger.exception("handle_callback_action failed")
        return {"ok": False, "action": "error", "approved": False, "error": str(e)}







