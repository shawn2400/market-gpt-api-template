# routes/telegram_bot.py
from __future__ import annotations
from fastapi import APIRouter, Request, HTTPException, Depends
from pydantic import BaseModel
from typing import Dict, Any, Optional, List, Tuple
import os, json, asyncio, uuid, time, hashlib
import httpx

from utils.auth import require_api_key
from utils.alerts import (
    send_telegram_message as send_message,
    edit_telegram_message as edit_message,
)
from utils.trade_models import TradeProposal, build_eta, summarize
from utils.eta import per_minute_move_estimate
from utils.get_klines import get_klines
from utils.indicators import prepare_indicators_for_backtest  # noqa: F401
from utils.ai_analysis import analyze_with_ai  # noqa: F401
from utils.liquidity import estimate_slippage
from utils.trade_validator import validate_proposal
from utils.approvals import preflight_proposal
from utils.runtime_prefs import (
    set_mute, clear_mute, mute_remaining_sec,
    set_near_pct_override, get_near_pct_override,
    set_trade_quiet, TelePrefs
)
from utils.hmac_utils import build_signed_outbound, generate_idempotency_key, sign_payload
from utils.binance_client import futures_mark_price  # ✅ שימוש ב-Mark Price

TPREFS = TelePrefs()

router_public = APIRouter(prefix="/telegram", tags=["Telegram"])
router = APIRouter(prefix="/telegram", tags=["Telegram"], dependencies=[Depends(require_api_key)])

PENDING: Dict[str, Dict[str, Any]] = {}

ALERTS_ACTIVE_URL = os.getenv("ALERTS_ACTIVE_URL", "http://127.0.0.1:8000/alerts/trades/active").strip()
ALERTS_UPDATE_URL = os.getenv("ALERTS_UPDATE_URL", "http://127.0.0.1:8000/alerts/trades/update").strip()
ALERTS_ANALYSIS_URL = os.getenv("ALERTS_ANALYSIS_URL", "http://127.0.0.1:8000/alerts/analysis").strip()
ALERTS_INGEST_URL = os.getenv("ALERTS_INGEST_URL", "http://127.0.0.1:8000/alerts/trade-ingest").strip()

RISK_QUICK_URL = os.getenv("RISK_QUICK_URL", "http://127.0.0.1:8000/risk/quick").strip()
WEBHOOK_HMAC_SECRET = os.getenv("WEBHOOK_HMAC_SECRET", "").strip()

DEFAULT_INTERVAL = os.getenv("DEFAULT_INTERVAL", "15m")
DEFAULT_MARKET = os.getenv("DEFAULT_MARKET", "futures")
TELEGRAM_WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()

APPROVAL_EARLY_AI = str(os.getenv("APPROVAL_EARLY_AI", "0")).lower() in ("1","true","yes","on")
PROPOSE_BLOCK_ON_FAIL = str(os.getenv("PROPOSE_BLOCK_ON_FAIL","0")).lower() in ("1","true","yes","on")

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

def _mk_tp_presets_keyboard(trade_id: str) -> dict:
    return {
        "inline_keyboard": [
            [{"text":"50/30/20", "callback_data":f"tppreset:{trade_id}:50:30:20"}],
            [{"text":"60/25/15", "callback_data":f"tppreset:{trade_id}:60:25:15"}],
            [{"text":"40/40/20", "callback_data":f"tppreset:{trade_id}:40:40:20"}],
        ]
    }

def _mk_main_keyboard(tid: str) -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": "✅ Approve", "callback_data": f"approve:{tid}"},
                {"text": "❌ Reject",  "callback_data": f"reject:{tid}"},
            ],
            [
                {"text": "✏️ Adjust", "callback_data": f"adjust:{tid}"},
                {"text": "🔒 SL→BE",   "callback_data": f"slbe:{tid}"},
            ],
            [
                {"text": "🎯 TP Presets", "callback_data": f"tpask:{tid}"},
            ]
        ]
    }

def _fmt_usd(x: float) -> str:
    return f"${x:,.2f}"

def _calc_size(entry: float, sl: float, leverage: int, budget_usd: float, risk_pct: float) -> Tuple[float, float, float]:
    entry = float(entry); sl = float(sl)
    leverage = max(1, int(leverage))
    budget_usd = max(1e-6, float(budget_usd))
    risk_dollars = max(0.0, budget_usd * float(risk_pct) / 100.0)
    delta = abs(entry - sl)
    if delta <= 0:
        raise ValueError("SL ו-Entry חייבים להיות שונים.")
    qty_risk = risk_dollars / delta
    qty_margin = (budget_usd * leverage) / entry
    qty = max(0.0, min(qty_risk, qty_margin))
    notional = qty * entry
    margin = notional / leverage
    return qty, notional, margin

def _summary_sig(items: List[Dict[str, Any]]) -> str:
    try:
        payload = [
            {
                "id": str(it.get("trade_id")),
                "sym": it.get("symbol"),
                "side": it.get("side"),
                "now": float(it.get("current_price") or 0.0),
                "tp1": float(it.get("tp1") or 0.0),
                "sl":  float(it.get("sl")  or 0.0),
            }
            for it in items
        ]
        if WEBHOOK_HMAC_SECRET:
            sig, ts = sign_payload(WEBHOOK_HMAC_SECRET, payload, prefix_scheme=True)
            short = sig.split("=",1)[-1][:10]
            return f"🔐 sig[{ts}]: sha256={short}"
        else:
            raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",",":")).encode("utf-8")
            short = hashlib.sha256(raw).hexdigest()[:10]
            return f"🔐 sig: sha256={short} (no-secret)"
    except Exception:
        return "🔐 sig: —"

@router.post("/set-webhook")
async def set_webhook(cfg: WebhookSet):
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise HTTPException(400, "missing TELEGRAM_BOT_TOKEN")
    secret = TELEGRAM_WEBHOOK_SECRET
    if not secret:
        raise HTTPException(400, "missing TELEGRAM_WEBHOOK_SECRET")
    api = f"https://api.telegram.org/bot{token}/setWebhook"
    payload = {"url": cfg.url, "secret_token": secret}
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(api, json=payload)
        try:
            r.raise_for_status()
        except Exception as e:
            raise HTTPException(r.status_code, f"telegram setWebhook failed: {e}; resp={r.text}")
        return r.json()

@router_public.post("/webhook")
async def webhook(request: Request):
    if TELEGRAM_WEBHOOK_SECRET:
        got = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not got or got.strip() != TELEGRAM_WEBHOOK_SECRET:
            raise HTTPException(status_code=403, detail="unauthorized")

    update = await request.json()

    # ----- messages -----
    if "message" in update:
        msg = update["message"]
        text = str(msg.get("text", "")).strip()
        chat_id = msg["chat"]["id"]
        mid = msg.get("message_id")

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
                "/summary [N]\n"
                "/pin_summary on|off  |  /bundle <sec>\n"
                "/snooze <minutes> <trade_id>  |  /snooze_sym <symbol> <minutes>\n"
                "/size <trade_id> <risk_pct>\n"
            )

        # ========== /propose ==========
        if text.startswith("/propose "):
            try:
                # /propose SYMBOL INTERVAL SIDE LEV ENTRY SL TP1 TP2 TP3 SUCCESS%
                parts = text.split()
                if len(parts) < 11:
                    return await send_message("⚠️ שימוש: /propose <symbol> <interval> <LONG|SHORT> <lev> <entry> <sl> <tp1> <tp2> <tp3> <success_pct>")
                _, symbol, interval, side, lev, entry, sl, tp1, tp2, tp3, succ = parts[:11]
                symbol = symbol.upper()

                # ✅ ממלאים current_price אוטומטית (fallback ל-entry אם אין)
                try:
                    nowp = futures_mark_price(symbol) or float(entry)
                except Exception:
                    nowp = float(entry)

                tid = uuid.uuid4().hex[:8].upper()
                tp_dict = {
                    "symbol": symbol,
                    "side": side.upper(),
                    "leverage": int(float(lev)),
                    "entry": float(entry),
                    "sl": float(sl),
                    "tp1": float(tp1),
                    "tp2": float(tp2),
                    "tp3": float(tp3),
                    "success_pct": float(succ),
                    "current_price": float(nowp),   # ✅
                    "budget": 30.0,                 # נשאר לצורכי preflight/sink
                }

                v = await validate_proposal(tp_dict, interval=interval, market=DEFAULT_MARKET)
                pre = preflight_proposal({**tp_dict, "interval": interval})
                if PROPOSE_BLOCK_ON_FAIL and not pre["ok"]:
                    lines = ["❌ ההצעה נדחתה (Preflight):", *[f"- {e}" for e in pre["errors"]]]
                    if pre.get("warnings"):
                        lines += ["", *[f"⚠️ {w}" for w in pre["warnings"]]]
                    return await send_message("\n".join(lines))

                PENDING[tid] = {"tp": tp_dict, "interval": interval}

                warn_lines = []
                if v.get("warnings"): warn_lines += [f"⚠️ {w}" for w in v["warnings"]]
                if pre.get("warnings"): warn_lines += [f"⚠️ {w}" for w in pre["warnings"]]
                pre_errs = pre.get("errors") or []
                pre_note = "✅ Preflight OK" if not pre_errs else "❗Preflight has issues (see below)"

                txt = (
                    f"📥 *Proposal* #{tid}\n"
                    f"{symbol} {side.upper()} x{int(float(lev))}\n"
                    f"Entry: `{float(entry):.6f}`  |  SL: `{float(sl):.6f}`\n"
                    f"TP1: `{float(tp1):.6f}`  |  TP2: `{float(tp2):.6f}`  |  TP3: `{float(tp3):.6f}`\n"
                    f"Now≈ `{float(nowp):.6f}`  |  Success≈ {float(succ):.1f}%\n"
                    f"{pre_note}"
                )
                if warn_lines or pre_errs:
                    txt += "\n\n" + "\n".join(warn_lines + [f"❌ {e}" for e in pre_errs])

                kb = _mk_main_keyboard(tid)
                return await send_message(txt + "\n\n(בחר פעולה מהכפתורים)", reply_markup=kb)
            except Exception as e:
                return await send_message(f"❌ שגיאה ב-/propose: {e}")

        # ----- המשך הפקודות הקיימות (ללא שינוי) -----
        # ... (נשאר כפי ששלחת; לא שיניתי מלבד הקטע של /propose)
        return await send_message("שלח /help לקבלת פורמט.")

    # ----- callbacks -----
    # (ללא שינוי מהגרסה שלך)
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
        # ... שאר ה-handlers נשארים זהים ...
        return {"ok": True}
    return {"ok": True}



















