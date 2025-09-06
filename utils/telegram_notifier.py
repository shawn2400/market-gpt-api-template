# utils/telegram_notifier.py
from __future__ import annotations
import os
import logging
import httpx
import asyncio
from typing import Dict, Any, Optional
from datetime import datetime

# אזור זמן: "Asia/Jerusalem" אם קיים, אחרת UTC
try:
    from zoneinfo import ZoneInfo  # Python 3.9+
    _TZ_IL = ZoneInfo("Asia/Jerusalem")
except Exception:
    _TZ_IL = None

logger = logging.getLogger("algogpt.telegram")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")

# =========================
# Utils
# =========================
def _fmt_pct(v: Optional[float], with_sign: bool = True) -> str:
    try:
        if v is None:
            return "—"
        if with_sign:
            # שימוש ב־+/- כולל מקף יוניקוד יפה (לא חובה)
            sign = "＋" if v >= 0 else "−"
            return f"{sign}{abs(v):.1f}%"
        return f"{v:.1f}%"
    except Exception:
        return str(v)

def _fmt_price(v: Optional[float]) -> str:
    try:
        if v is None:
            return "—"
        # הפרדת אלפים בסגנון 25,090
        if abs(v) >= 100:
            return f"{v:,.0f}"
        return f"{v:,.2f}"
    except Exception:
        return str(v)

def _now_il_str() -> str:
    try:
        if _TZ_IL:
            dt = datetime.now(_TZ_IL)
            return dt.strftime("%d/%m/%Y | %H:%M")
        # Fallback: UTC
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

# =========================
# Card Builder
# =========================
def _build_trade_card(decision: Dict[str, Any]) -> str:
    """
    יוצר טקסט כרטיס טרייד בפורמט המדויק שביקשת.
    מצופה לקבל לפחות:
      symbol, side, budget, leverage, tp1_pct, tp2_pct, tp3_pct, sl_pct,
      eta_tp1_min, quality_score, price, expires_min
    """
    symbol   = (decision.get("symbol") or "UNKNOWN").upper()
    side     = (decision.get("side") or "LONG").upper()
    budget   = decision.get("budget", None)
    leverage = decision.get("leverage", None)
    tp1_pct  = decision.get("tp1_pct", None)
    tp2_pct  = decision.get("tp2_pct", None)
    tp3_pct  = decision.get("tp3_pct", None)
    sl_pct   = decision.get("sl_pct", None)
    eta_min  = decision.get("eta_tp1_min", None)
    quality  = decision.get("quality_score", None)
    price    = decision.get("price", None)
    exp_min  = decision.get("expires_min", None)

    # אייקון לפי כיוון
    side_icon = "🟢" if side == "LONG" else "🔴" if side == "SHORT" else "🟦"

    # טיימסטמפ
    ts = _now_il_str()

    # שורות
    header = f"📅 {ts} (שעון ישראל)\n\n🚀 AlgoGPT — טרייד חדש ({symbol})\n"
    body = []
    body.append(f"{side_icon} כיוון: {side}")
    if budget is not None:
        body.append(f"💵 השקעה: {_fmt_price(float(budget))} USDT")
    if leverage is not None:
        body.append(f"⚖️ מינוף: ×{int(leverage)}")

    # TP/SL
    tp_line = f"🎯 TP1={_fmt_pct(tp1_pct)} | TP2={_fmt_pct(tp2_pct)} | TP3={_fmt_pct(tp3_pct)}"
    sl_line = f"🛡️ SL: {_fmt_pct(-abs(sl_pct) if (sl_pct is not None) else None)}"  # להציג שלילי יפה

    body.append(tp_line)
    body.append(sl_line)
    body.append("")  # רווח

    # ETA/Quality/Price/Expiry
    if eta_min is not None:
        body.append(f"⏱️ זמן ל־TP1: ~{int(eta_min)} דק׳")
    if quality is not None:
        body.append(f"📊 איכות: {float(quality):.1f}/10")
    if price is not None:
        body.append(f"📈 מחיר שוק: {_fmt_price(float(price))} USDT")
    if exp_min is not None:
        # המרה פשוטה לדקות→שעות אם צריך
        try:
            exp_min = int(exp_min)
            if exp_min >= 120 and exp_min % 60 == 0:
                body.append(f"⏳ תפוגה: {exp_min // 60} שעות")
            elif exp_min >= 60:
                hrs = exp_min // 60
                mins = exp_min % 60
                body.append(f"⏳ תפוגה: {hrs} ש׳ {mins} ד׳")
            else:
                body.append(f"⏳ תפוגה: {exp_min} דק׳")
        except Exception:
            body.append(f"⏳ תפוגה: {exp_min} דק׳")

    # אפשרות להוסיף סיכום AI כטקסט מסכם (אופציונלי)
    ai_summary = (decision.get("ai_summary") or "").strip()
    if ai_summary:
        body.append("")
        body.append(ai_summary)

    return header + "\n".join(body)

# =========================
# Public API
# =========================
async def notify_trade_proposal(decision: Dict[str, Any], with_buttons: bool = True) -> None:
    """
    שולח כרטיס טרייד מלא עם התבנית החדשה.
    אם with_buttons=True – מוסיף כפתורי אישור/דחייה (Callback).
    """
    text = _build_trade_card(decision)
    payload: Dict[str, Any] = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",  # הטקסט בנוי להיות ידידותי ל־Markdown רגיל
        "disable_web_page_preview": True,
    }
    if with_buttons:
        symbol = (decision.get("symbol") or "UNKNOWN").upper()
        side   = (decision.get("side") or "LONG").upper()
        payload["reply_markup"] = {
            "inline_keyboard": [[
                {"text": "✅ אישור", "callback_data": f"approve:{symbol}:{side}"},
                {"text": "❌ ביטול", "callback_data": f"reject:{symbol}:{side}"},
            ]]
        }
    await _post_telegram(payload)

async def notify_info(text: str) -> None:
    """
    הודעת סטטוס קצרה (ללא כפתורים), לשימוש בשלבים:
    “✅ אושר…”, “📤 נשלח לביצוע…”, “🟢 Binance אישר…”, “טרייד פעיל…” וכו'.
    """
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }
    await _post_telegram(payload)

async def notify_external_signal(payload: Dict[str, Any]) -> None:
    """
    התראת מקור חיצוני (TradingView/קבוצות/אחר) — Notify בלבד.
    לא פותח טריידים.
    """
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



