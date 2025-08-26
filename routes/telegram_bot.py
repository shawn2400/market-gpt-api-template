# routes/telegram_bot.py
from __future__ import annotations
from fastapi import APIRouter, Request, HTTPException, Depends, Query
from pydantic import BaseModel
from typing import Dict, Any, Optional
import os, json, asyncio, time, uuid, httpx

from utils.auth import require_api_key
from utils.telegram_api import send_message, edit_message
from utils.trade_models import TradeProposal, build_eta, summarize
from utils.eta import per_minute_move_estimate
from utils.get_klines import get_klines
from utils.indicators import prepare_indicators_for_backtest
from utils.ai_analysis import analyze_with_ai
from utils.liquidity import liquidity_gate
from utils.risk_rules import rr_from_levels, leverage_cap, kelly_suggestion
from utils.redis_client import redis_client as RED

router = APIRouter(prefix="/telegram", tags=["Telegram"], dependencies=[Depends(require_api_key)])

PENDING: Dict[str, Dict] = {}

CONTEXT_URL = os.getenv("CONTEXT_URL","").strip()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN","").strip()
CHAT_ID_DEFAULT = os.getenv("TELEGRAM_CHAT_ID", os.getenv("ADMIN_CHAT_ID","").strip())
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else ""
TIMEOUT = float(os.getenv("TELEGRAM_HTTP_TIMEOUT","15"))

# --- helpers to read active trades (prefer Redis via trade_sink) ---
def _load_trade_by_id(tid: str) -> Optional[Dict[str, Any]]:
    # אם trade_sink רץ עם Redis:
    if RED:
        key = f"trades:active:{tid}"
        try:
            d = RED.hgetall(key)
            if d:
                # שחזור שדות JSON
                for k in ("hits","near","grid_lines"):
                    if k in d and isinstance(d[k], str):
                        try: d[k] = json.loads(d[k])
                        except Exception: pass
                # המרה מספרית לשדות ידועים
                def fnum(x):
                    try: return float(x)
                    except Exception: return None
                for k in ("current_price","entry","sl","tp1","tp2","tp3","success_pct","notional_usd","budget_usd"):
                    if k in d: d[k] = fnum(d[k])
                if "leverage" in d:
                    try: d["leverage"] = int(d["leverage"])
                    except Exception: pass
                return d
        except Exception:
            pass
    # fallback: בקשה ל-API שלך
    try:
        url = os.getenv("ALERTS_ACTIVE_URL","http://127.0.0.1:8000/alerts/trades/active")
        r = httpx.get(url, timeout=8)
        r.raise_for_status()
        items = r.json().get("items",[])
        for it in items:
            if str(it.get("trade_id")) == tid:
                return it
    except Exception:
        pass
    return None

async def _context_single(symbol: str, interval: str = "15m") -> Dict[str, Any]:
    if not CONTEXT_URL:
        return {}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(CONTEXT_URL.rstrip("/") + "/context", params={"symbol":symbol, "interval":interval, "compact":True})
            r.raise_for_status()
            return r.json()
    except Exception:
        return {}

class WebhookSet(BaseModel):
    url: str

@router.post("/set-webhook")
async def set_webhook(cfg: WebhookSet):
    if not BOT_TOKEN: raise HTTPException(400, "missing TELEGRAM_BOT_TOKEN")
    api = f"{TELEGRAM_API}/setWebhook"
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(api, json={"url": cfg.url})
        return r.json()

@router.post("/webhook")
async def webhook(request: Request):
    update = await request.json()

    if "message" in update:
        msg = update["message"]
        text = str(msg.get("text","")).strip()
        chat_id = msg["chat"]["id"]

        # --- commands ---
        if text.startswith("/start"):
            return await send_message("🤖 AlgoGPT Bot מוכן. שלח /help לקבלת הוראות.")
        if text.startswith("/help"):
            return await send_message(
                "פקודות:\n"
                "/propose BTCUSDT 15m LONG 10 65000 64500 66170 67400 68800 72.5\n"
                "↳ פורמט: {symbol} {interval} {side} {lev} {entry} {sl} {tp1} {tp2} {tp3} {success%}\n"
                "/auto_on | /auto_off — הדלקת הצעות GPT אוטומטיות\n"
                "/approve <id> | /reject <id>\n"
                "/liquidity <symbol> <notional_usd> <LONG|SHORT>\n"
                "/risk <trade_id>  — RR/lev-cap/Kelly להצע הקיימת"
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

        # --- NEW: /liquidity SYM NOTIONAL SIDE ---
        if text.startswith("/liquidity"):
            try:
                _, sym, notional, side = text.split(maxsplit=3)
                notional = float(notional)
                g = liquidity_gate(sym, side, notional_usd=notional)
                if g.get("ok"):
                    m = (
                        f"💧 *Liquidity OK* for *{sym}* {side}\n"
                        f"Notional: ${notional:,.2f}\n"
                        f"Est. slippage: ~{g.get('slippage_pct',0):.3f}%"
                    )
                else:
                    m = (
                        f"⚠️ *Liquidity FAIL* for *{sym}* {side}\n"
                        f"Notional: ${notional:,.2f}\n"
                        f"Reason: `{g.get('reason','unknown')}`"
                    )
                return await send_message(m)
            except Exception as e:
                return await send_message(f"❌ שגיאת פורמט: /liquidity BTCUSDT 10000 LONG\n({e})")

        # --- NEW: /risk <trade-id> ---
        if text.startswith("/risk"):
            parts = text.split()
            if len(parts) != 2:
                return await send_message("שימוש: /risk <trade-id>")
            tid = parts[1].strip()
            rec = _load_trade_by_id(tid)
            if not rec:
                return await send_message(f"לא נמצא טרייד id={tid}")
            sym = rec.get("symbol")
            side = rec.get("side","LONG").upper()
            entry = rec.get("entry")
            sl = rec.get("sl")
            tp1 = rec.get("tp1")
            lev = int(rec.get("leverage") or 10)
            sp  = rec.get("success_pct")

            # vol_regime לצורך lev-cap
            ctx = await _context_single(sym)
            vol_reg = (ctx.get("filters") or {}).get("vol_regime","mid")
            rr = rr_from_levels(side, entry, sl, tp1) if (entry and sl and tp1) else None
            lev_cap = leverage_cap(vol_reg)
            kelly = kelly_suggestion(sp or 50.0, rr or 1.6)

            m = [
                f"📊 *Risk for #{tid}* — *{sym}* {side}",
                f"Entry: `{entry}`  SL: `{sl}`  TP1: `{tp1}`  Lev: x{lev}",
                f"RR≈*{rr if rr is not None else '—'}*  •  Vol regime: *{vol_reg}*  •  Lev cap: *x{lev_cap}*",
                f"Kelly (capped): *{kelly*100:.1f}%* of bankroll",
            ]
            if lev > lev_cap:
                m.append("⚠️ מינוף מעל תקרת המשטר — שקול הפחתה.")
            if rr is not None and rr < 1.6:
                m.append("⚠️ RR נמוך — שקול כיוונון רמות (ATR/BB).")
            return await send_message("\n".join(m))

        # --- Manual proposal (קיים) ---
        if text.startswith("/propose"):
            try:
                parts = text.split()
                symbol, interval, side, lev, entry, sl, tp1, tp2, tp3, succ = parts[1:11]
                lev = int(lev); entry=float(entry); sl=float(sl); tp1=float(tp1)
                tp2=float(tp2); tp3=float(tp3); succ=float(succ)
                df = await get_klines(symbol, interval=interval, limit=50, market="futures")
                price = float(df["close"].iloc[-1])
                vol_per_min = per_minute_move_estimate(df) / (15 if "15" in interval else 1)
                tp = TradeProposal(
                    symbol=symbol, side=side, current_price=price, leverage=lev,
                    entry=entry, sl=sl, tp1=tp1, tp2=tp2, tp3=tp3, success_pct=succ
                )
                eta = build_eta(tp, per_min_move=vol_per_min)
                tid = uuid.uuid4().hex[:8]
                PENDING[tid] = {"tp": tp.dict(), "eta": eta.dict(), "interval": interval}
                txt = summarize(tp, eta, why="הוזן ידנית ע״י המשתמש")
                kb = {"inline_keyboard":[
                    [{"text":"✅ אשר", "callback_data":f"approve:{tid}"},
                     {"text":"✏️ כוונן", "callback_data":f"adjust:{tid}"},
                     {"text":"🛑 דחה", "callback_data":f"reject:{tid}"}]
                ]}
                return await send_message(txt, kb)
            except Exception as e:
                return await send_message(f"❌ קלט לא תקין: {e}")

        # not recognized
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

async def _approve_trade_id(tid: str, chat_id: int, message_id: Optional[int]):
    item = PENDING.get(tid)
    if not item:
        return await send_message(f"⚠️ טרייד {tid} לא קיים/פג תוקף")
    tp = TradeProposal(**item["tp"])
    exec_trades = (os.getenv("EXECUTE_TRADES","false").lower() in ("1","true","yes"))
    details = ("🔐 מצב הדמיה/ידני (לא נשלח לבינאנס)\n" if not exec_trades else "🚀 מבצע הזמנה בבינאנס...\n")
    txt = summarize(tp, build_eta(tp, per_min_move=0), why=details)
    if message_id:
        return await edit_message(chat_id, message_id, txt)
    else:
        return await send_message(txt)


