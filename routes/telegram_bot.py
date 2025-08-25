# routes/telegram_bot.py
from __future__ import annotations
from fastapi import APIRouter, Request, HTTPException, Depends, Query
from pydantic import BaseModel
from utils.auth import require_api_key
from utils.telegram_api import send_message, edit_message, approve_keyboard
from utils.trade_models import TradeProposal, build_eta, summarize
from utils.eta import per_minute_move_estimate
from utils.get_klines import get_klines
from utils.indicators import prepare_indicators_for_backtest
from utils.ai_analysis import analyze_with_ai
import os, json, asyncio, time, uuid

router = APIRouter(prefix="/telegram", tags=["Telegram"], dependencies=[Depends(require_api_key)])

# זיכרון זמני לטריידים ממתינים לאישור
PENDING: dict[str, dict] = {}

class WebhookSet(BaseModel):
    url: str

@router.post("/set-webhook")
async def set_webhook(cfg: WebhookSet):
    # מגדיר webhook בבוט
    import httpx, os
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token: raise HTTPException(400, "missing TELEGRAM_BOT_TOKEN")
    api = f"https://api.telegram.org/bot{token}/setWebhook"
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(api, json={"url": cfg.url})
        return r.json()

@router.post("/webhook")  # <-- URL זה תרשום אצל BotFather באמצעות /set-webhook
async def webhook(request: Request):
    update = await request.json()
    # תומך במסרים רגילים ו-callback של כפתורים
    if "message" in update:
        msg = update["message"]
        text = str(msg.get("text", "")).strip()
        chat_id = msg["chat"]["id"]
        if text.startswith("/start"):
            return await send_message("🤖 AlgoGPT Bot מוכן. שלח /help לקבלת הוראות.")
        if text.startswith("/help"):
            return await send_message(
                "פקודות:\n"
                "/propose BTCUSDT 15m LONG 10 65000 64500 66170 67400 68800 72.5\n"
                "↳ פורמט: {symbol} {interval} {side} {lev} {entry} {sl} {tp1} {tp2} {tp3} {success%}\n"
                "/auto_on  | /auto_off — הדלקת הצעות GPT אוטומטיות\n"
                "/approve <id> | /reject <id>"
            )
        if text.startswith("/auto_on"):
            os.environ["TRADE_AUTO_SUGGEST"] = "1"
            return await send_message("🟢 Auto-Suggest הופעל")
        if text.startswith("/auto_off"):
            os.environ["TRADE_AUTO_SUGGEST"] = "0"
            return await send_message("🔴 Auto-Suggest כובה")
        if text.startswith("/approve "):
            tid = text.split(maxsplit=1)[1].strip()
            return await _approve_trade_id(tid, chat_id, msg.get("message_id"))
        if text.startswith("/reject "):
            tid = text.split(maxsplit=1)[1].strip()
            PENDING.pop(tid, None)
            return await send_message(f"❌ טרייד {tid} נדחה")

        if text.startswith("/propose"):
            # קלט ידני מהמשתמש (בפורמט קצר) → בונה הצעה
            try:
                parts = text.split()
                # /propose BTCUSDT 15m LONG 10 65000 64500 66170 67400 68800 72.5
                symbol, interval, side, lev, entry, sl, tp1, tp2, tp3, succ = parts[1:11]
                lev = int(lev); entry=float(entry); sl=float(sl); tp1=float(tp1)
                tp2=float(tp2); tp3=float(tp3); succ=float(succ)
                # מחיר נוכחי מהשוק
                df = await get_klines(symbol, interval=interval, limit=50, market="futures")
                price = float(df["close"].iloc[-1])
                vol_per_min = per_minute_move_estimate(df) / (15 if "15" in interval else 1)  # נרמל גס אם 15m
                tp = TradeProposal(
                    symbol=symbol, side=side, current_price=price, leverage=lev,
                    entry=entry, sl=sl, tp1=tp1, tp2=tp2, tp3=tp3, success_pct=succ
                )
                eta = build_eta(tp, per_min_move=vol_per_min)
                tid = uuid.uuid4().hex[:8]
                PENDING[tid] = {"tp": tp.dict(), "eta": eta.dict(), "interval": interval}
                txt = summarize(tp, eta, why="הוזן ידנית ע״י המשתמש")
                kb = {"inline_keyboard":[[
                    {"text":"✅ אשר", "callback_data":f"approve:{tid}"},
                    {"text":"✏️ כוונן", "callback_data":f"adjust:{tid}"},
                    {"text":"🛑 דחה", "callback_data":f"reject:{tid}"}
                ]]}
                return await send_message(txt, kb)
            except Exception as e:
                return await send_message(f"❌ קלט לא תקין: {e}")

        # פקודה לא מזוהה → התעלמות, או שלח help
        return await send_message("שלח /help לקבלת פורמט.")

    if "callback_query" in update:
        cq = update["callback_query"]
        data = cq.get("data","")
        chat_id = cq["message"]["chat"]["id"]
        mid = cq["message"]["message_id"]
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
        return {"ok": True}

    return {"ok": True}

async def _approve_trade_id(tid: str, chat_id: int, message_id: int|None):
    item = PENDING.get(tid)
    if not item:
        return await send_message(f"⚠️ טרייד {tid} לא קיים/פג תוקף")
    tp = TradeProposal(**item["tp"])
    # אם EXECUTE_TRADES=true → לבצע, אחרת רק להציג פרטי הזמנה “מוכנים”
    exec_trades = (os.getenv("EXECUTE_TRADES","false").lower() in ("1","true","yes"))
    details = (
        "🔐 מצב הדמיה/ידני (לא נשלח לבינאנס)\n"
        if not exec_trades else
        "🚀 מבצע הזמנה בבינאנס...\n"
    )
    txt = summarize(tp, build_eta(tp, per_min_move=0), why=details)  # ETA נוסף לא הכרחי כאן
    # TODO: חיבור אמיתי ל-binance_futures_trade אם exec_trades=True
    if message_id:
        return await edit_message(chat_id, message_id, txt)
    else:
        return await send_message(txt)
