# routes/telegram_bot.py
from __future__ import annotations
from fastapi import APIRouter, Request, HTTPException, Depends
from pydantic import BaseModel
from typing import Dict, Any, Optional, List
import os, json, asyncio, uuid
import httpx

from utils.auth import require_api_key
from utils.telegram_api import send_message, edit_message
from utils.trade_models import TradeProposal, build_eta, summarize
from utils.eta import per_minute_move_estimate
from utils.get_klines import get_klines
from utils.indicators import prepare_indicators_for_backtest
from utils.ai_analysis import analyze_with_ai
from utils.liquidity import estimate_slippage

from utils.runtime_prefs import (
    set_mute, clear_mute, mute_remaining_sec,
    set_near_pct_override, get_near_pct_override,
    set_trade_quiet,
)

router = APIRouter(prefix="/telegram", tags=["Telegram"], dependencies=[Depends(require_api_key)])

PENDING: Dict[str, Dict[str, Any]] = {}

ALERTS_ACTIVE_URL = os.getenv("ALERTS_ACTIVE_URL", "http://127.0.0.1:8000/alerts/trades/active").strip()
ALERTS_UPDATE_URL = os.getenv("ALERTS_UPDATE_URL", "http://127.0.0.1:8000/alerts/trades/update").strip()
ALERTS_ANALYSIS_URL = os.getenv("ALERTS_ANALYSIS_URL", "http://127.0.0.1:8000/alerts/analysis").strip()
RISK_QUICK_URL = os.getenv("RISK_QUICK_URL", "http://127.0.0.1:8000/risk/quick").strip()

DEFAULT_INTERVAL = os.getenv("DEFAULT_INTERVAL", "15m")
DEFAULT_MARKET = os.getenv("DEFAULT_MARKET", "futures")

class WebhookSet(BaseModel):
    url: str

async def _load_trade_by_id(tid: str) -> Optional[Dict[str, Any]]:
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
    if tid in PENDING:
        d = PENDING[tid]
        return {"trade_id": tid, **d.get("tp", {})}
    return None

def _mk_slbe_keyboard(trade_id: str) -> dict:
    return {"inline_keyboard": [[{"text": "🔒 SL→BE", "callback_data": f"slbe:{trade_id}"}]]}

def _mk_tp_presets_keyboard(trade_id: str) -> dict:
    return {
        "inline_keyboard": [
            [{"text":"50/30/20", "callback_data":f"tppreset:{trade_id}:50:30:20"}],
            [{"text":"60/25/15", "callback_data":f"tppreset:{trade_id}:60:25:15"}],
            [{"text":"40/40/20", "callback_data":f"tppreset:{trade_id}:40:40:20"}],
        ]
    }

@router.post("/set-webhook")
async def set_webhook(cfg: WebhookSet):
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise HTTPException(400, "missing TELEGRAM_BOT_TOKEN")
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
        mid = msg.get("message_id")

        # ---------- HELP ----------
        if text.startswith("/start"):
            return await send_message("🤖 AlgoGPT Bot מוכן. שלח /help לקבלת הוראות.")
        if text.startswith("/help"):
            return await send_message(
                "פקודות:\n"
                "/propose BTCUSDT 15m LONG 10 65000 64500 66170 67400 68800 72.5\n"
                "/auto_on | /auto_off\n"
                "/approve <id> | /reject <id>\n"
                "/tp_scale <id> 50 30 20  |  /sl_be <id>\n"
                "/liquidity <symbol> <notional_usd> <side>\n"
                "/risk <trade-id>\n"
                "/mute <minutes> | /unmute | /set_near <pct>\n"
                "/quiet_on <id> | /quiet_off <id>\n"
                "/summary [N]  — סיכום טריידים פעילים (ברירת מחדל N=15)\n"
            )

        # ---------- AUTO ----------
        if text.startswith("/auto_on"):
            os.environ["TRADE_AUTO_SUGGEST"] = "1"
            return await send_message("🟢 Auto-Suggest הופעל.")
        if text.startswith("/auto_off"):
            os.environ["TRADE_AUTO_SUGGEST"] = "0"
            return await send_message("🔴 Auto-Suggest כובה.")

        # ---------- APPROVE/REJECT ----------
        if text.startswith("/approve "):
            tid = text.split(maxsplit=1)[1].strip()
            return await _approve_trade_id(tid, chat_id, mid)
        if text.startswith("/reject "):
            tid = text.split(maxsplit=1)[1].strip()
            PENDING.pop(tid, None)
            return await send_message(f"❌ טרייד {tid} נדחה")

        # ---------- TP SCALE / SL->BE ----------
        if text.startswith("/tp_scale "):
            try:
                _, tid, p1, p2, p3 = text.split()
                p = [float(p1), float(p2), float(p3)]
                if abs(sum(p) - 100.0) > 1e-6:
                    return await send_message("⚠️ הסכום חייב להיות 100 (למשל 50 30 20).")
                async with httpx.AsyncClient(timeout=10) as client:
                    r = await client.post(ALERTS_UPDATE_URL, json={
                        "trade_id": tid, "updates": {"tp_scale": json.dumps(p)}
                    })
                    r.raise_for_status()
                return await send_message(f"✅ TP Scale ל-#{tid}: {int(p[0])}/{int(p[1])}/{int(p[2])}%")
            except Exception as e:
                return await send_message(f"❌ שימוש: /tp_scale <id> <p1> <p2> <p3>\n({e})")

        if text.startswith("/sl_be "):
            try:
                _, tid = text.split(maxsplit=1)
                rec = await _load_trade_by_id(tid)
                if not rec: return await send_message(f"לא נמצא טרייד id={tid}")
                entry = rec.get("entry")
                if entry is None: return await send_message("אין entry מוגדר להצעה זו.")
                async with httpx.AsyncClient(timeout=10) as client:
                    r = await client.post(ALERTS_UPDATE_URL, json={
                        "trade_id": tid, "updates": {"sl": float(entry)}
                    })
                    r.raise_for_status()
                return await send_message(f"🔒 SL הוגדר ל-BE ({float(entry):.6f}) ב-#{tid}")
            except Exception as e:
                return await send_message(f"❌ שימוש: /sl_be <id>\n({e})")

        # ---------- LIQUIDITY ----------
        if text.startswith("/liquidity "):
            try:
                _, sym, notional, side = text.split()
                notional = float(notional)
                res = await estimate_slippage(sym, side, notional)
                if not res.get("ok"):
                    return await send_message(f"❌ {res.get('error','liquidity error')}")
                msg = (
                    f"💧 *Liquidity* {sym.upper()} {side.upper()} ${int(notional)}\n"
                    f"Mid: `{res['mid_price']:.6f}`  Avg Fill: `{res['avg_fill_price']:.6f}`\n"
                    f"Slippage: *{res['slippage_pct']:.3f}%*"
                )
                return await send_message(msg)
            except Exception as e:
                return await send_message(f"❌ שימוש: /liquidity <symbol> <notional_usd> <side>\n({e})")

        # ---------- RISK ----------
        if text.startswith("/risk "):
            try:
                _, tid = text.split(maxsplit=1)
                async with httpx.AsyncClient(timeout=10) as client:
                    r = await client.get(RISK_QUICK_URL, params={"trade_id": tid})
                    r.raise_for_status()
                    data = r.json()
                if not data.get("ok"):
                    return await send_message("❌ risk: not ok")
                rr = data.get("rr"); rr_s = f"{rr:.2f}" if rr else "—"
                k = data.get("kelly_fraction"); k_s = f"{k*100:.1f}%" if k is not None else "—"
                lev = data.get("leverage_cap") or "—"
                msg = (
                    f"🛡️ *Risk* #{tid}\n"
                    f"{data['symbol']} {data['side']}\n"
                    f"Entry: `{data['entry']:.6f}`  SL: `{data['sl']:.6f}`  TP1: `{(data['tp1'] or 0):.6f}`\n"
                    f"RR≈ *{rr_s}*  |  Kelly≈ *{k_s}*  |  Lev Cap≈ *x{lev}*\n"
                    f"Success: ~{(data.get('success_pct') or 0):.1f}%"
                )
                return await send_message(msg)
            except Exception as e:
                return await send_message(f"❌ שימוש: /risk <trade-id>\n({e})")

        # ---------- MUTE / NEAR ----------
        if text.startswith("/mute "):
            try:
                _, mins = text.split(maxsplit=1)
                mins = max(1, int(mins))
                set_mute(mins)
                return await send_message(f"🔕 הושתק ל-{mins} דק׳ (נותר {mute_remaining_sec()}ש׳).")
            except Exception as e:
                return await send_message(f"❌ שימוש: /mute <minutes>\n({e})")

        if text.startswith("/unmute"):
            clear_mute()
            return await send_message("🔔 התראות הופעלו.")

        if text.startswith("/set_near "):
            try:
                _, pct = text.split(maxsplit=1)
                pct = float(pct)
                set_near_pct_override(pct)
                return await send_message(f"📏 near-pct נקבע ל-{pct:.2f}%")
            except Exception as e:
                return await send_message(f"❌ שימוש: /set_near <pct>\n({e})")

        # ---------- QUIET per trade ----------
        if text.startswith("/quiet_on "):
            try:
                _, tid = text.split(maxsplit=1)
                set_trade_quiet(tid, True)
                return await send_message(f"😶 near-alerts כובו לטרייד #{tid}")
            except Exception as e:
                return await send_message(f"❌ שימוש: /quiet_on <id>\n({e})")

        if text.startswith("/quiet_off "):
            try:
                _, tid = text.split(maxsplit=1)
                set_trade_quiet(tid, False)
                return await send_message(f"🔊 near-alerts הופעלו לטרייד #{tid}")
            except Exception as e:
                return await send_message(f"❌ שימוש: /quiet_off <id>\n({e})")

        # ---------- SUMMARY ----------
        if text.startswith("/summary"):
            try:
                parts = text.split()
                limit = int(parts[1]) if len(parts) > 1 else 15
                async with httpx.AsyncClient(timeout=10) as client:
                    r = await client.get(ALERTS_ACTIVE_URL)
                    r.raise_for_status()
                    items = r.json().get("items", [])
                # דירוג לפי הכי קרוב ל-TP1/SL
                def dist(it):
                    nowp = float(it.get("current_price") or 0)
                    tp1 = it.get("tp1"); tp1 = float(tp1) if tp1 else None
                    sl  = it.get("sl");  sl  = float(sl)  if sl  else None
                    d1 = abs(nowp - tp1)/tp1 if (nowp and tp1) else 9e9
                    ds = abs(nowp - sl)/sl   if (nowp and sl)  else 9e9
                    return min(d1, ds)
                items = sorted(items, key=dist)[:limit]
                lines: List[str] = ["📋 *Active Summary*"]
                for it in items:
                    sym = it.get("symbol","")
                    side = it.get("side","")
                    nowp = float(it.get("current_price") or 0)
                    tp1  = it.get("tp1"); tp1 = float(tp1) if tp1 else None
                    sl   = it.get("sl");  sl  = float(sl)  if sl  else None
                    d1 = f"{abs(nowp-tp1)/tp1*100:.2f}%" if (nowp and tp1) else "—"
                    ds = f"{abs(nowp-sl)/sl*100:.2f}%"   if (nowp and sl)  else "—"
                    lines.append(f"- {sym} {side}: Now `{nowp:.6f}` | ΔTP1 {d1} | ΔSL {ds}")
                return await send_message("\n".join(lines))
            except Exception as e:
                return await send_message(f"❌ שגיאה ב-/summary: {e}")

        # ---------- PROPOSE (ידני) ----------
        if text.startswith("/propose"):
            try:
                parts = text.split()
                symbol, interval, side, lev, entry, sl, tp1, tp2, tp3, succ = parts[1:11]
                lev = int(lev); entry=float(entry); sl=float(sl); tp1=float(tp1)
                tp2=float(tp2); tp3=float(tp3); succ=float(succ)
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
                            {"text":"✅ אשר","callback_data":f"approve:{tid}"},
                            {"text":"✏️ כוונן","callback_data":f"adjust:{tid}"},
                            {"text":"🛑 דחה","callback_data":f"reject:{tid}"}
                        ],
                        [
                            {"text":"🔒 SL→BE","callback_data":f"slbe:{tid}"},
                            {"text":"📊 TP Presets","callback_data":f"tpask:{tid}"}
                        ]
                    ]
                }
                return await send_message(txt, kb)
            except Exception as e:
                return await send_message(f"❌ קלט לא תקין: {e}")

        return await send_message("שלח /help לקבלת פורמט.")

    # ---------- CALLBACKS ----------
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
            rec = await _load_trade_by_id(tid)
            if not rec:
                p = PENDING.get(tid, {}).get("tp", {})
                entry = p.get("entry")
                if entry is None:
                    return await edit_message(chat_id, mid, "⚠️ אין entry מוגדר להצעה זו.")
                return await edit_message(chat_id, mid, "🔒 SL→BE יתבצע לאחר שהצעה תאושר ותיכנס ל-sink.")
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

        if data.startswith("tpask:"):
            tid = data.split(":",1)[1]
            text = f"בחר פריסט או שלח ידנית:\n`/tp_scale {tid} 50 30 20` (סה\"כ 100)\n"
            kb = _mk_tp_presets_keyboard(tid)
            return await edit_message(chat_id, mid, text, kb)

        if data.startswith("tppreset:"):
            try:
                _, tid, a, b, c = data.split(":")
                p = [float(a), float(b), float(c)]
                if abs(sum(p)-100.0) > 1e-6:
                    return await edit_message(chat_id, mid, "⚠️ סכום הפריסט אינו 100")
                async with httpx.AsyncClient(timeout=10) as client:
                    r = await client.post(ALERTS_UPDATE_URL, json={
                        "trade_id": tid, "updates": {"tp_scale": json.dumps(p)}
                    })
                    r.raise_for_status()
                return await edit_message(chat_id, mid, f"✅ נקבע TP Scale {int(p[0])}/{int(p[1])}/{int(p[2])}%")
            except Exception as e:
                return await edit_message(chat_id, mid, f"❌ שגיאה בפריסט: {e}")

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
    kb = _mk_slbe_keyboard(tid)
    if message_id:
        return await edit_message(chat_id, message_id, txt, kb)
    else:
        return await send_message(txt, kb)




