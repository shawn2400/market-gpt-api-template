# routes/telegram_bot.py (תוספת פקודות: /hours /funding /grid_plan /status)
from __future__ import annotations
from fastapi import APIRouter, Request, HTTPException, Depends
from pydantic import BaseModel
from utils.auth import require_api_key
from utils.telegram_api import send_message, edit_message
from utils.trade_models import TradeProposal, build_eta, summarize
from utils.eta import per_minute_move_estimate
from utils.get_klines import get_klines
from utils.indicators import prepare_indicators_for_backtest
from utils.ai_analysis import analyze_with_ai
from utils.trade_store import create_trade, get_trade, update_trade
from utils.hours_profile import hours_profile_now
from utils.funding_bias import get_funding_cached
from utils.grid_planner import plan_grid
import os, uuid

router = APIRouter(prefix="/telegram", tags=["Telegram"], dependencies=[Depends(require_api_key)])
PENDING: dict[str, dict] = {}

class WebhookSet(BaseModel):
    url: str

@router.post("/set-webhook")
async def set_webhook(cfg: WebhookSet):
    import httpx, os
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token: raise HTTPException(400, "missing TELEGRAM_BOT_TOKEN")
    api = f"https://api.telegram.org/bot{token}/setWebhook"
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(api, json={"url": cfg.url})
        return r.json()

@router.post("/webhook")
async def webhook(request: Request):
    update = await request.json()
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
                "/auto_on | /auto_off\n"
                "/approve <id> | /reject <id>\n"
                "/hours — סטטוס Hot/Idle + פרמטרים\n"
                "/funding <symbol>\n"
                "/grid_plan <symbol> <budget_usd> [levels=6] [step_pct=0.8] [side=LONG]\n"
                "/status"
            )
        if text.startswith("/hours"):
            prof = hours_profile_now()
            return await send_message(
                f"🕒 {'HOT' if prof['hot'] else 'IDLE'} | topK={prof['topk']} | cooldown={prof['cooldown_min']}m | rr_bonus={prof['rr_bonus']}"
            )
        if text.startswith("/funding"):
            parts = text.split()
            if len(parts)<2: return await send_message("שימוש: /funding BTCUSDT")
            sym = parts[1].upper()
            v = get_funding_cached(sym)
            if not v: return await send_message("אין נתונים כרגע.")
            rate, ts = v
            return await send_message(f"📊 Funding {sym}: {rate*100:.4f}%")
        if text.startswith("/grid_plan"):
            parts = text.split()
            if len(parts)<3: return await send_message("שימוש: /grid_plan <symbol> <budget_usd> [levels] [step_pct] [side]")
            sym   = parts[1].upper()
            bud   = float(parts[2])
            lvls  = int(parts[3]) if len(parts)>3 else 6
            step  = float(parts[4]) if len(parts)>4 else 0.8
            side  = parts[5].upper() if len(parts)>5 else "LONG"
            df = await get_klines(sym, interval="15m", limit=2, market="futures")
            price = float(df["close"].iloc[-1])
            plan = plan_grid(price, bud, lvls, step, side)
            lines = [f"🧩 Grid Plan {sym} {side} @ {price:.6f}"]
            for it in plan["levels"]:
                lines.append(f"  L{it['level']}: {it['price']:.6f}  | ${it['alloc_usd']:.2f}")
            lines.append(f"TP≈ {plan['tp']:.6f} | SL≈ {plan['sl']:.6f}")
            return await send_message("\n".join(lines))

        if text.startswith("/status"):
            prof = hours_profile_now()
            return await send_message(f"Status: {'HOT' if prof['hot'] else 'IDLE'} | Interval={os.getenv('DEFAULT_INTERVAL','15m')}")

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
            try:
                parts = text.split()
                symbol, interval, side, lev, entry, sl, tp1, tp2, tp3, succ = parts[1:11]
                lev = int(lev); entry=float(entry); sl=float(sl); tp1=float(tp1); tp2=float(tp2); tp3=float(tp3); succ=float(succ)
                df = await get_klines(symbol, interval=interval, limit=50, market="futures")
                price = float(df["close"].iloc[-1])
                vol_per_min = per_minute_move_estimate(df) / (15 if "15" in interval else 1)
                tp = TradeProposal(symbol=symbol, side=side, current_price=price, leverage=lev,
                                   entry=entry, sl=sl, tp1=tp1, tp2=tp2, tp3=tp3, success_pct=succ)
                eta = build_eta(tp, per_min_move=vol_per_min)
                tid = uuid.uuid4().hex[:8]
                PENDING[tid] = {"tp": tp.dict(), "eta": eta.dict(), "interval": interval, "chat_id": chat_id}
                txt = summarize(tp, eta, why="הוזן ידנית ע״י המשתמש")
                kb = {"inline_keyboard":[
                    [{"text":"✅ אשר", "callback_data":f"approve:{tid}"},
                     {"text":"✏️ כוונן", "callback_data":f"adjust:{tid}"},
                     {"text":"🛑 דחה", "callback_data":f"reject:{tid}"}]
                ]}
                return await send_message(txt, kb)
            except Exception as e:
                return await send_message(f"❌ קלט לא תקין: {e}")

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
        if data.startswith("slbe:"):
            tid = data.split(":",1)[1]
            return await _sl_to_be(tid, chat_id, mid)
        return {"ok": True}

    return {"ok": True}

async def _approve_trade_id(tid: str, chat_id: int, message_id: int|None):
    item = PENDING.get(tid)
    if not item:
        return await send_message(f"⚠️ טרייד {tid} לא קיים/פג תוקף")
    tp = TradeProposal(**item["tp"])
    details = ("🔐 מצב הדמיה/ידני — לא נשלח לבינאנס\n"
               if not (os.getenv("EXECUTE_TRADES","false").lower() in ("1","true","yes"))
               else "🚀 מבצע הזמנה בבינאנס...\n")
    txt = summarize(tp, build_eta(tp, per_min_move=0), why=details)
    trade_payload = {
        "id": tid, "symbol": tp.symbol, "chat_id": item.get("chat_id"),
        "interval": item.get("interval","15m"),
        "proposal": {"trade_type": "FUTURES", "side": tp.side, "entry": tp.entry, "sl": tp.sl,
                     "tp1": tp.tp1, "tp2": tp.tp2, "tp3": tp.tp3, "leverage": tp.leverage,
                     "success_pct": tp.success_pct},
        "status": "TRACKED"
    }
    create_trade(trade_payload)
    if message_id: return await edit_message(chat_id, message_id, txt)
    return await send_message(txt)

async def _sl_to_be(tid: str, chat_id: int, message_id: int|None):
    tr = get_trade(tid)
    if not tr: return await edit_message(chat_id, message_id, f"⚠️ טרייד {tid} לא נמצא")
    entry = float(tr.get("proposal",{}).get("entry") or 0)
    if entry<=0: return await edit_message(chat_id, message_id, f"⚠️ טרייד {tid}: לא נמצא מחיר כניסה")
    update_trade(tid, {"proposal": {**tr["proposal"], "sl": entry}})
    txt = (
        f"🔒 עדכון SL → BE ב־<b>{tr['symbol']}</b>\n"
        f"סטופ חדש: <b>{entry:.6f}</b>\n\n"
        "הנחיות ידניות:\n"
        "1) Binance > Positions\n"
        "2) עדכן Stop Loss למחיר הנ״ל\n"
        "3) אשר ושמור"
    )
    return await edit_message(chat_id, message_id, txt)

