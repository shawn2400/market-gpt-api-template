# utils/health_tp1.py
import os, asyncio, logging
from typing import List, Dict, Any
from contextlib import suppress

from utils.binance_client import get_all_orders
from utils.trade_execution_core import BOT_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_PARSE_MODE
import httpx

log = logging.getLogger("algogpt.health.tp1")

TP1_TAGS_ENV = [t.strip() for t in (os.getenv("TP1_TAGS", "") or "").split(",") if t.strip()]

async def _tg_send(text: str) -> Dict[str, Any]:
    chat_id = int(os.getenv("TRADE_LOG_CHAT_ID") or TELEGRAM_CHAT_ID or 0)
    token = os.getenv("TELEGRAM_BOT_TOKEN") or BOT_TOKEN
    if not (chat_id and token):
        return {"ok": False, "skipped": True, "reason": "no_chat_or_token"}
    payload = {"chat_id": chat_id, "text": text, "parse_mode": TELEGRAM_PARSE_MODE or "HTML", "disable_web_page_preview": True}
    try:
        async with httpx.AsyncClient(timeout=10.0) as cli:
            r = await cli.post(f"https://api.telegram.org/bot{token}/sendMessage", json=payload)
        return r.json()
    except Exception as e:
        log.warning("telegram_send_failed: %s", e)
        return {"ok": False, "error": str(e)}

def _tp_orders(symbol: str) -> List[Dict[str, Any]]:
    try:
        lst = get_all_orders(symbol, limit=100) or []
        return [o for o in lst if str(o.get("type","")).upper().startswith("TAKE_PROFIT")]
    except Exception:
        return []

def _has_tp1_tag(order: Dict[str, Any]) -> bool:
    coi  = str(order.get("clientOrderId") or "")
    name = str(order.get("origClientOrderId") or "")
    s = (coi + "|" + name).upper()
    tags = TP1_TAGS_ENV if TP1_TAGS_ENV else ["TP1"]
    return any(tag.upper() in s for tag in tags)

async def health_check_tp1_tags(symbols: List[str], *, interval_sec: int = 600) -> None:
    """רץ בלופ; אם יש הזמנות TP אך אף אחת לא מזוהה כ-TP1 לפי תגית/שם — תתריע."""
    await asyncio.sleep(5.0)
    while True:
        try:
            for sym in symbols:
                tps = _tp_orders(sym)
                if not tps:
                    continue
                if not any(_has_tp1_tag(o) for o in tps):
                    await _tg_send(
                        f"⚠️ <b>TP1 tag health</b>\n"
                        f"• {sym}: נמצאו הזמנות TP אך ללא תגית/שם מזוהה כ-TP1.\n"
                        f"• עדכן <code>TP1_TAGS</code> או clientOrderId (למשל TP1)."
                    )
        except Exception as e:
            log.warning("health_check_tp1_tags_error: %s", e)
        await asyncio.sleep(max(60, interval_sec))
