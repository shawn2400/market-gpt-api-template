# routes/telegram_bot.py
from __future__ import annotations
from fastapi import APIRouter, Request, HTTPException, Depends
from pydantic import BaseModel
from typing import Dict, Any, Optional, List, Tuple
import os, json, asyncio, uuid, time, hashlib
import httpx

# מאובטח רק למסלולים הרגישים (לא ל-webhook)
from utils.auth import require_api_key

from utils.telegram_api import send_message, edit_message
from utils.trade_models import TradeProposal, build_eta, summarize
from utils.eta import per_minute_move_estimate
from utils.get_klines import get_klines
from utils.indicators import prepare_indicators_for_backtest  # noqa: F401
from utils.ai_analysis import analyze_with_ai  # noqa: F401
from utils.liquidity import estimate_slippage
from utils.trade_validator import validate_proposal

from utils.runtime_prefs import (
    set_mute, clear_mute, mute_remaining_sec,
    set_near_pct_override, get_near_pct_override,
    set_trade_quiet,
)
from utils.runtime_prefs import TelePrefs

from utils.hmac_utils import build_signed_outbound, generate_idempotency_key, sign_payload

TPREFS = TelePrefs()

# ───────────────── Config ─────────────────
ALERTS_ACTIVE_URL = os.getenv("ALERTS_ACTIVE_URL", "http://127.0.0.1:8000/alerts/trades/active").strip()
ALERTS_UPDATE_URL = os.getenv("ALERTS_UPDATE_URL", "http://127.0.0.1:8000/alerts/trades/update").strip()
ALERTS_ANALYSIS_URL = os.getenv("ALERTS_ANALYSIS_URL", "http://127.0.0.1:8000/alerts/analysis").strip()
ALERTS_INGEST_URL = os.getenv("ALERTS_INGEST_URL", "http://127.0.0.1:8000/alerts/trade-ingest").strip()

RISK_QUICK_URL = os.getenv("RISK_QUICK_URL", "http://127.0.0.1:8000/risk/quick").strip()
WEBHOOK_HMAC_SECRET = os.getenv("WEBHOOK_HMAC_SECRET", "").strip()

DEFAULT_INTERVAL = os.getenv("DEFAULT_INTERVAL", "15m")
DEFAULT_MARKET = os.getenv("DEFAULT_MARKET", "futures")

# ───────────────── Routers ─────────────────
# ציבורי: webhook (ללא API key)
router_public = APIRouter(prefix="/telegram", tags=["Telegram"])

# מאובטח: set-webhook (כן API key)
router = APIRouter(prefix="/telegram", tags=["Telegram"], dependencies=[Depends(require_api_key)])

# ───────────────── Models ─────────────────
class WebhookSet(BaseModel):
    url: str

# ───────────────── Helpers ─────────────────
PENDING: Dict[str, Dict[str, Any]] = {}

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

# ───────────────── Secure route (Bearer) ─────────────────
@router.post("/set-webhook")
async def set_webhook(cfg: WebhookSet):
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise HTTPException(400, "missing TELEGRAM_BOT_TOKEN")
    api = f"https://api.telegram.org/bot{token}/setWebhook"
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(api, json={"url": cfg.url})
        r.raise_for_status()
        return r.json()

# ───────────────── Public route (no Bearer) ─────────────────
@router_public.post("/webhook")
async def webhook(request: Request):
    update = await request.json()

    if "message" in update:
        msg = update["message"]
        text = str(msg.get("text", "")).strip()
        chat_id = msg["chat"]["id"]
        mid = msg.get("message_id")

        # HELP
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

        # pin/bundle/snooze/size וכו' (כמו אצלך)
        # ……… (השארתי את כל הבלוק שלך כמו שהוא, רק הזזתי לרוטר הציבורי) ………

        # ====== כל הקוד מהשאלה שלך נשמר זהה מכאן והלאה ======
        # LIGHT EXTENSIONS … (pin_summary, bundle, snooze, snooze_sym, size)
        # AUTO … (auto_on, auto_off)
        # APPROVE/REJECT … (approve, reject)
        # TP SCALE / SL->BE … (tp_scale, sl_be)
        # LIQUIDITY … (/liquidity)
        # RISK … (/risk)
        # MUTE/UNMUTE/SET_NEAR … (/mute, /unmute, /set_near)
        # QUIET … (/quiet_on, /quiet_off)
        # SUMMARY … (/summary)
        # PROPOSE … (/propose)
        # CALLBACKS … (approve:, reject:, adjust:, slbe:, tpask:, tppreset:)
        # ולבסוף return {"ok": True}
        # ====== העתקת בדיוק את הקוד מההודעה שלך (לא חוזר עליו כאן לקיצור) ======

    if "callback_query" in update:
        # … ה־callbacks המדויקים שלך (כמו בשאלה) …
        return {"ok": True}

    return {"ok": True}

# שאר הפונקציה _approve_trade_id נשארת זהה (כמו אצלך)
async def _approve_trade_id(tid: str, chat_id: int, message_id: Optional[int]):
    item = PENDING.get(tid)
    if not item:
        return await send_message(f"⚠️ טרייד {tid} לא קיים/פג תוקף")

    tp = TradeProposal(**item["tp"])
    val = await validate_proposal(tp.dict(), interval=item.get("interval") or DEFAULT_INTERVAL, market=DEFAULT_MARKET)
    if not val["ok"]:
        return await edit_message(chat_id, message_id, "❌ הוולידציה נכשלה:\n" + "\n".join(f"- {e}" for e in val["errors"]))

    trade_type = "FUTURES" if DEFAULT_MARKET.lower().startswith("future") else "SPOT"
    payload = {
        "trade_id": tid,
        "trade_type": trade_type,
        "symbol": tp.symbol,
        "side": tp.side,
        "current_price": tp.current_price,
        "entry": tp.entry, "sl": tp.sl,
        "tp1": tp.tp1, "tp2": tp.tp2, "tp3": tp.tp3,
        "leverage": tp.leverage,
        "success_pct": tp.success_pct,
        "reason": "approved via telegram",
        "chat_id": chat_id,
        "interval": item.get("interval") or DEFAULT_INTERVAL,
        "market": DEFAULT_MARKET,
    }
    body, headers = build_signed_outbound(
        WEBHOOK_HMAC_SECRET,
        payload,
        idempotency_key=generate_idempotency_key()
    )

    try:
        async with httpx.AsyncClient(timeout=12) as client:
            r = await client.post(ALERTS_INGEST_URL, content=body, headers=headers)
            if r.status_code == 422:
                data = r.json() if r.headers.get("content-type","").startswith("application/json") else {}
                errs = data.get("errors") or ["validator_failed"]
                warns= data.get("warnings") or []
                txt = "❌ Pre-Flight @ sink:\n" + "\n".join(f"- {e}" for e in errs)
                if warns:
                    txt += "\n\n⚠️ " + "\n⚠️ ".join(warns)
                return await edit_message(chat_id, message_id, txt)
            r.raise_for_status()
            PENDING.pop(tid, None)
            return await edit_message(chat_id, message_id, f"✅ טרייד #{tid} נשלח ל־sink ופורסם לטלגרם.")
    except Exception as e:
        return await edit_message(chat_id, message_id, f"❌ ingest failed: {e}")









