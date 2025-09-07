# utils/telegram_notifier.py
from __future__ import annotations
import os, logging, httpx
from typing import Dict, Any
from datetime import datetime
try:
    from zoneinfo import ZoneInfo
    _TZ_IL = ZoneInfo("Asia/Jerusalem")
except Exception:
    _TZ_IL = None

logger = logging.getLogger("algogpt.telegram")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")

def _now_il_str() -> str:
    if _TZ_IL:
        return datetime.now(_TZ_IL).strftime("%d/%m/%Y | %H:%M")
    return datetime.utcnow().strftime("%d/%m/%Y | %H:%M")

async def _post(text: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID: return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    async with httpx.AsyncClient(timeout=15.0) as client:
        await client.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True
        })

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

async def notify_info(text: str): await _post(text)
async def notify_error(text: str): await _post(f"⚠️ Error: {text}")
async def notify_heartbeat(): await _post(f"🟢 Heartbeat {_now_il_str()}: AlgoGPT חי ונושם")
async def notify_daily_summary(summary: Dict[str, Any]):
    text = f"📊 Daily Summary {_now_il_str()}\nPnL: {summary['pnl']:.2f} USDT\nTrades: {len(summary['trades'])}"
    await _post(text)
async def notify_trade_review(symbol: str, review: str): await _post(f"✍️ Review {symbol}: {review}")





