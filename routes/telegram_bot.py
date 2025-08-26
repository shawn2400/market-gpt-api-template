# routes/telegram_bot.py
from __future__ import annotations
from fastapi import APIRouter, Request, HTTPException, Depends
from pydantic import BaseModel
from typing import Dict, Any, Optional
import os, json, asyncio, time, uuid

import httpx

from utils.auth import require_api_key
from utils.telegram_api import send_message, edit_message  # approve_keyboard לא נדרש כאן
from utils.trade_models import TradeProposal, build_eta, summarize
from utils.eta import per_minute_move_estimate
from utils.get_klines import get_klines
from utils.indicators import prepare_indicators_for_backtest
from utils.ai_analysis import analyze_with_ai

router = APIRouter(prefix="/telegram", tags=["Telegram"], dependencies=[Depends(require_api_key)])

# זיכרון זמני להצעות ידניות שממתינות לאישור
PENDING: Dict[str, Dict[str, Any]] = {}

# --- קונפיג מה-ENV (ללא תלות ב-main)
ALERTS_ACTIVE_URL = os.getenv("ALERTS_ACTIVE_URL", "http://127.0.0.1:8000/alerts/trades/active").strip()
ALERTS_UPDATE_URL = os.getenv("ALERTS_UPDATE_URL", "http://127.0.0.1:8000/alerts/trades/update").strip()
ALERTS_ANALYSIS_URL = os.getenv("ALERTS_ANALYSIS_URL", "http://127.0.0.1:8000/alerts/analysis").strip()

DEFAULT_INTERVAL = os.getenv("DEFAULT_INTERVAL", "15m")
DEFAULT_MARKET = os.getenv("DEFAULT_MARKET", "futures")

# ------------ Models ------------
class WebhookSet(BaseModel):
    url: str

# ------------ Helpers ------------
async def _load_trade_by_id(tid: str) -> Optional[Dict[str, Any]]:
    """
    מושך את רשימת הטריידים הפעילים מה-sink ומאתר לפי trade_id.
    """
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(ALERTS_ACTIVE_URL)
            r.raise_for_status()
            items = r.json().get("items", [])
        for it in items:
            if str(it.get("trade_id")) == str(tid):
                return it
    except Exception:
        pass
    # fallback להצעות ידניות שלא נכנסו ל-sink:
    if tid in PENDING:
        d = PENDING[tid]
        return {"trade_id": tid, **d.get("tp", {})}
    return None

def _mk_slbe_keyboard(trade_id: str) -> dict:
    return {"inline_keyboard": [[
        {"text": "🔒 SL→BE", "callback_data": f"slbe:{trade_id}"},
    ]]}

# ------------ Routes ------------
@router.post("/set-webhook")
async def set_webhook(cfg: WebhookSet):
    """
    רושם webhook לבוט בטלגרם (צריך TELEGRAM_BOT_TOKEN ב-ENV).
    """
    import os
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise HTTPException(400, "missing TELEGRAM_BOT_TOKEN")
    api = f"https://api.telegram.org/bot{token}/setWebhook"
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(api, json={"url": cfg.url})
        return r.json()

@router.post("/webhook")
async def webhook(request: Request):
    """
    נקודת כניסה מ-Telegram: מטפלת במסרים ובלחיצות כפתורים (callback_query).
    """
    update = await request.json()

    # --- הודעות טקסט
    if "message" in update:
        msg = update["message"]
        text = str(msg.get("text", "")).strip()
        chat_id = msg["chat"]["id"]
        mid = msg.get("message_id")

        if text.startswith("/start"):
            return await send_message("🤖 AlgoGPT Bot מוכן. שלח /help לקבלת הוראות.")
        if text.startswith("/help"):
            return await send_message(
                "פקודות עיקריות:\n"
                "/propose BTCUSDT 15m LONG 10 65000 64500 66170 67400 68800 72.5\n"
                "↳ פורמט: {symbol} {interval} {side} {lev} {entry} {sl} {tp1} {tp2} {tp3} {success%}\n"
                "/auto_on | /auto_off — הדלקת/כיבוי הצעות GPT אוטומטיות\n"
                "/approve <id> | /reject <id>\n"
                "/tp_scale <id> <p1> <p2> <p3> — חלוקת כמות בין היעדים (למשל 50 30 20)\n"
                "/sl_be <id> — קבע Stop-Loss ל-Break-Even (שווה ל-entry)\n"
                "טיפים: ניתן לאשר/לדחות מהכפתורים בהודעה; כפתור SL→BE יופיע אוטומטית בהגעה ל-TP1."
            )

        if text.startswith("/auto_on"):
            os.environ["TRADE_AUTO_SUGGEST"] = "1"
            return await send_message("🟢 Auto-Suggest הופעל (הוורקר יתחיל להציע טריידים).")
        if text.startswith("/auto_off"):
            os.environ["TRADE_AUTO_SUGGEST"] = "0"
            return await send_message("🔴 Auto-Suggest כובה.")

        if text.startswith("/approve "):
            tid = text.split(maxsplit=1)[1].strip()
            return await _approve_trade_id(tid, chat_id, mid)

        if text.startswith("/reject "):
            tid = text.split(maxsplit=1)[1].strip()
            PENDING.pop(tid, None)
            return await send_message(f"❌ טרייד {tid} נדחה")

        if text.startswith("/tp_scale "):
            # /tp_scale <id> 50 30 20
            try:
                _, tid, p1, p2, p3 = text.split()
                p = [float(p1), float(p2), float(p3)]
                if abs(sum(p) - 100.0) > 1e-6:
                    return await send_message("⚠️ הסכום חייב להיות 100 (למשל 50 30 20).")
                # נשמור ב-sink לשימוש ניהול פוזיציה (watchdog/אוטו-מנהל בעתיד)
                async with httpx.AsyncClient(timeout=10) as client:
                    r = await client.post(ALERTS_UPDATE_URL, json={
                        "trade_id": tid,
                        "updates": {"tp_scale": json.dumps(p)}
                    })
                    r.raise_for_status()
                return await send_message(f"✅ נשמרה חלוקת TP ל-#{tid}: {int(p[0])}/{int(p[1])}/{int(p[2])}%")
            except Exception as e:
                return await send_message(f"❌ שימוש: /tp_scale <id> <p1> <p2> <p3>\n({e})")

        if text.startswith("/sl_be "):
            # /sl_be <id> — קובע SL ל-entry
            try:
                _, tid = text.split(maxsplit=1)
                rec = await _load_trade_by_id(tid)
                if not rec: return await send_message(f"לא נמצא טרייד id={tid}")
                entry = rec.get("entry")
                if entry is None: return await send_message("אין entry מוגדר להצעה זו.")
                async with httpx.AsyncClient(timeout=10) as client:
                    r = await client.post(ALERTS_UPDATE_URL, json={
                        "trade_id": tid,
                        "updates": {"sl": float(entry)}
                    })
                    r.raise_for_status()
                return await send_message(f"🔒 SL הוגדר ל-BE ({float(entry):.6f}) ב-#{tid}")
            except Exception as e:
                return await send_message(f"❌ שימוש: /sl_be <id>\n({e})")

        if text.startswith("/propose"):
            # קלט ידני: /propose BTCUSDT 15m LONG 10 65000 64500 66170 67400 68800 72.5
            try:
                parts = text.split()
                symbol, interval, side, lev, entry, sl, tp1, tp2, tp3, succ = parts[1:11]
                lev = int(lev); entry=float(entry); sl=float(sl); tp1=float(tp1)
                tp2=float(tp2); tp3=float(tp3); succ=float(succ)

                # מחיר נוכחי מהשוק (לפי interval)
                df = await get_klines(symbol, interval=interval or DEFAULT_INTERVAL, limit=50, market=DEFAULT_MARKET)
                price = float(df["close"].iloc[-1])
                vol_per_min = per_minute_move_estimate(df) / (15 if "15" in (interval or "15m") else 1)

                tp = TradeProposal(
                    symbol=symbol.upper(), side=side.upper(), current_price=price,
                    leverage=lev, entry=entry, sl=sl, tp1=tp1, tp2=tp2, tp3=tp3, success_pct=succ
                )
                eta = build_eta(tp, per_min_move=vol_per_min)
                tid = uuid.uuid4().hex[:8]
                PENDING[tid] = {"tp": tp.dict(), "eta": eta.dict(), "interval": interval}

                txt = summarize(tp, eta, why="הוזן ידנית ע״י המשתמש")
                kb = {
                    "inline_keyboard":[
                        [
                            {"text":"✅ אשר", "callback_data":f"approve:{tid}"},
                            {"text":"✏️ כוונן", "callback_data":f"adjust:{tid}"},
                            {"text":"🛑 דחה", "callback_data":f"reject:{tid}"}
                        ],
                        [
                            {"text":"🔒 SL→BE", "callback_data":f"slbe:{tid}"},
                            {"text":"📊 TP Scale", "callback_data":f"tpask:{tid}"}
                        ]
                    ]
                }
                return await send_message(txt, kb)
            except Exception as e:
                return await send_message(f"❌ קלט לא תקין: {e}")

        # פקודה לא מזוהה
        return await send_message("שלח /help לקבלת פורמט.")

    # --- לחיצות כפתור (callback_query)
    if "callback_query" in update:
        cq = update["callback_query"]
        data = cq.get("data","")
        chat_id = cq["message"]["chat"]["id"]
        mid = cq["message"]["message_id"]

        # אישור/דחייה/כוונון להצעות ידניות (PENDING)
        if data.startswith("approve:"):
            tid = data.split(":",1)[1]
            return await _approve_trade_id(tid, chat_id, mid)
        if data.startswith("reject:"):
            tid = data.split(":",1)[1]
            PENDING.pop(tid, None)
            return await edit_message(chat_id, mid, f"❌ טרייד {tid} נדחה")
        if data.startswith("adjust:"):
            tid = data.split(":",1)[1]
            return await edit_message(chat_id, mid, f"✏️ טרייד {tid} — שלח /propose עם ערכים מעודכנים.")

        # --- חדש: כפתור SL→BE (גם מה-watchdog, גם מהצעת /propose)
        if data.startswith("slbe:"):
            tid = data.split(":",1)[1]
            rec = await _load_trade_by_id(tid)
            if not rec:
                # יתכן שזה PENDING בלבד
                p = PENDING.get(tid, {}).get("tp", {})
                entry = p.get("entry")
                if entry is None:
                    return await edit_message(chat_id, mid, "⚠️ אין entry מוגדר להצעה זו.")
                # עדכון רק בטקסט (אין sink)
                return await edit_message(chat_id, mid, "🔒 SL→BE יקבע לאחר שהצעה תאושר ותיכנס ל-sink.")
            entry = rec.get("entry")
            if entry is None:
                return await edit_message(chat_id, mid, "⚠️ אין entry מוגדר להצעה זו.")
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    r = await client.post(ALERTS_UPDATE_URL, json={
                        "trade_id": tid, "updates": {"sl": float(entry)}
                    })
                    r.raise_for_status()
                return await edit_message(chat_id, mid, f"🔒 SL הוגדר ל-BE ({float(entry):.6f}) ב-#{tid}")
            except Exception as e:
                return await edit_message(chat_id, mid, f"❌ שגיאה בהגדרת SL→BE: {e}")

        # --- חדש: בקשה להגדרת TP Scale מתוך כפתור
        if data.startswith("tpask:"):
            tid = data.split(":",1)[1]
            text = (
                f"🔧 הזן חלוקת TP ל-#{tid} בפורמט:\n"
                f"`/tp_scale {tid} 50 30 20`\n"
                f"(הסכום חייב להיות 100)"
            )
            return await edit_message(chat_id, mid, text)

        return {"ok": True}

    return {"ok": True}

# -------- Internal approve helper --------
async def _approve_trade_id(tid: str, chat_id: int, message_id: Optional[int]):
    """
    מציג סיכום “מוכן להזמנה” להצעה ידנית (PENDING).
    אין כאן שליחה לבינאנס — רק טקסט/ETA מפורט.
    """
    item = PENDING.get(tid)
    if not item:
        return await send_message(f"⚠️ טרייד {tid} לא קיים/פג תוקף")
    tp = TradeProposal(**item["tp"])

    exec_trades = (os.getenv("EXECUTE_TRADES","false").lower() in ("1","true","yes"))
    details = ("🔐 מצב הדמיה/ידני (לא נשלח לבינאנס)\n" if not exec_trades else "🚀 מבצע הזמנה בבינאנס...\n")
    txt = summarize(tp, build_eta(tp, per_min_move=0), why=details)

    # הוספת כפתור SL→BE גם כאן
    kb = _mk_slbe_keyboard(tid)

    if message_id:
        return await edit_message(chat_id, message_id, txt, kb)
    else:
        return await send_message(txt, kb)



