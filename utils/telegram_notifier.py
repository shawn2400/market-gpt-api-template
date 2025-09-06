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

# ===== Utils =====
def _fmt_pct(v: Optional[float], with_sign: bool = True) -> str:
    try:
        if v is None: return "—"
        sign = "＋" if v >= 0 else "−"
        return f"{sign}{abs(v):.1f}%" if with_sign else f"{v:.1f}%"
    except Exception:
        return str(v)

def _fmt_price(v: Optional[float]) -> str:
    try:
        if v is None: return "—"
        return f"{v:,.0f}" if abs(v) >= 100 else f"{v:,.2f}"
    except Exception:
        return str(v)

def _now_il_str() -> str:
    try:
        if _TZ_IL:
            return datetime.now(_TZ_IL).strftime("%d/%m/%Y | %H:%M")
        return datetime.utcnow().strftime("%d/%m/%Y | %H:%M")
    except Exception:
        return ""

async def _post_telegram(payload: Dict[str, Any]) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram not configured (missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID)")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            await client.post(url, json=payload)
    except Exception as e:
        logger.error(f"Telegram send failed: {e}")

# ===== Card Builder =====
def _build_trade_card(decision: Dict[str, Any]) -> str:
    symbol   = (decision.get("symbol") or "UNKNOWN").upper()
    side     = (decision.get("side") or "LONG").upper()
    side_icon = "🟢" if side == "LONG" else "🔴" if side == "SHORT" else "🟦"

    header = f"📅 {_now_il_str()} (שעון ישראל)\n\n🚀 AlgoGPT — טרייד חדש ({symbol})\n"
    body = [
        f"{side_icon} כיוון: {side}",
    ]
    if decision.get("budget") is not None:
        body.append(f"💵 השקעה: {_fmt_price(float(decision['budget']))} USDT")
    if decision.get("leverage") is not None:
        body.append(f"⚖️ מינוף: ×{int(decision['leverage'])}")

    body.append(f"🎯 TP1={_fmt_pct(decision.get('tp1_pct'))} | TP2={_fmt_pct(decision.get('tp2_pct'))} | TP3={_fmt_pct(decision.get('tp3_pct'))}")
    body.append(f"🛡️ SL: {_fmt_pct(-abs(decision['sl_pct']) if decision.get('sl_pct') else None)}")

    if decision.get("eta_tp1_min") is not None:
        body.append(f"⏱️ זמן ל־TP1: ~{int(decision['eta_tp1_min'])} דק׳")
    if decision.get("quality_score") is not None:
        body.append(f"📊 איכות: {float(decision['quality_score']):.1f}/10")
    if decision.get("price") is not None:
        body.append(f"📈 מחיר שוק: {_fmt_price(float(decision['price']))} USDT")
    if decision.get("expires_min") is not None:
        exp_min = int(decision['expires_min'])
        if exp_min >= 60:
            hrs, mins = divmod(exp_min, 60)
            body.append(f"⏳ תפוגה: {hrs} ש׳ {mins} ד׳")
        else:
            body.append(f"⏳ תפוגה: {exp_min} דק׳")

    if decision.get("ai_summary"):
        body.append("")
        body.append(decision["ai_summary"].strip())

    return header + "\n".join(body)

# ===== Public API =====
async def notify_trade_proposal(decision: Dict[str, Any], with_buttons: bool = True) -> None:
    text = _build_trade_card(decision)
    payload: Dict[str, Any] = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }
    if with_buttons:
        symbol, side = decision.get("symbol","UNKNOWN").upper(), decision.get("side","LONG").upper()
        payload["reply_markup"] = {
            "inline_keyboard": [[
                {"text": "✅ אישור", "callback_data": f"approve:{symbol}:{side}"},
                {"text": "❌ ביטול", "callback_data": f"reject:{symbol}:{side}"},
            ]]
        }
    await _post_telegram(payload)

async def notify_info(text: str) -> None:
    await _post_telegram({
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    })

async def notify_external_signal(payload: Dict[str, Any]) -> None:
    try:
        pretty = payload if isinstance(payload, dict) else {"data": str(payload)}
        text = f"🌐 External Signal (Notify-Only)\n```\n{pretty}\n```"
        await _post_telegram({
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        })
    except Exception as e:
        logger.error(f"notify_external_signal failed: {e}")




