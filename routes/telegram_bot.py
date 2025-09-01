# routes/telegram_bot.py
from __future__ import annotations
from fastapi import APIRouter, Request, HTTPException, Depends
from pydantic import BaseModel
from typing import Dict, Any, Optional, List, Tuple
import os, json, asyncio, uuid, time, hashlib

import httpx

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
    set_trade_quiet, TelePrefs
)
TPREFS = TelePrefs()

from utils.hmac_utils import build_signed_outbound, generate_idempotency_key, sign_payload

# ──────────────────────────────────────────────────────────────────────────────
# Routers: public (webhook) + secure (set-webhook)
# ──────────────────────────────────────────────────────────────────────────────
router_public = APIRouter(prefix="/telegram", tags=["Telegram"])  # ללא require_api_key
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

TELEGRAM_WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()  # ← חשוב

# --------- Models ----------
class WebhookSet(BaseModel):
    url: str

# --------- Helpers ----------
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

# ───────── Secure route: set webhook (Bearer required) ─────────
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

# ───────── Public route: webhook receiver (validates secret header) ─────────
@router_public.post("/webhook")
async def webhook(request: Request):
    # אימות כותרת מהטלגרם
    if TELEGRAM_WEBHOOK_SECRET:
        got = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not got or got.strip() != TELEGRAM_WEBHOOK_SECRET:
            # לא נחשוף יותר מדי לוגיקה
            return {"ok": False, "error": "unauthorized"}

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
                "/summary [N]\n"
                "/pin_summary on|off  |  /bundle <sec>\n"
                "/snooze <minutes> <trade_id>  |  /snooze_sym <symbol> <minutes>\n"
                "/size <trade_id> <risk_pct>\n"
            )

        # ---------- LIGHT EXTENSIONS ----------
        if text.startswith("/pin_summary"):
            parts = text.split()
            if len(parts) != 2 or parts[1].lower() not in ("on", "off"):
                return await send_message("שימוש: /pin_summary on|off")
            on = (parts[1].lower() == "on")
            await TPREFS.set_pin_summary(chat_id, on)
            if not on:
                await TPREFS.set_pin_message_id(chat_id, None)
            else:
                resp = await send_message("📌 סיכום מוצמד יופיע כאן. המערכת תעדכן ב־edit.")
                try:
                    if isinstance(resp, dict) and resp.get("message_id"):
                        await TPREFS.set_pin_message_id(chat_id, int(resp["message_id"]))
                except Exception:
                    pass
            return await send_message(f"pin_summary: {'ON' if on else 'OFF'}")

        if text.startswith("/bundle"):
            parts = text.split()
            if len(parts) == 1:
                sec = await TPREFS.get_bundle_window(chat_id)
                return await send_message(f"bundle={sec}s  (שימוש: /bundle <seconds>, 0=כבוי)")
            try:
                sec = max(0, int(parts[1]))
            except Exception as e:
                return await send_message(f"❌ שימוש: /bundle <seconds>\n({e})")
            await TPREFS.set_bundle_window(chat_id, sec)
            return await send_message(f"Bundling {'ON' if sec>0 else 'OFF'} ({sec}s)")

        if text.startswith("/snooze "):
            try:
                _, mins, tid = text.split(maxsplit=2)
                mins = int(mins)
                await TPREFS.snooze_trade(tid, mins)
                return await send_message(f"🔕 Snooze לטרייד {tid} ל-{mins} דק׳ הופעל.")
            except Exception as e:
                return await send_message(f"❌ שימוש: /snooze <minutes> <trade_id>\n({e})")

        if text.startswith("/snooze_sym "):
            try:
                _, sym, mins = text.split(maxsplit=2)
                mins = int(mins)
                await TPREFS.snooze_symbol(sym, mins)
                return await send_message(f"🔕 Snooze לסימבול {sym.upper()} ל-{mins} דק׳ הופעל.")
            except Exception as e:
                return await send_message(f"❌ שימוש: /snooze_sym <symbol> <minutes>\n({e})")

        if text.startswith("/size "):
            try:
                _, tid, rpct = text.split(maxsplit=2)
                rpct = float(rpct)
                rec = await _load_trade_by_id(tid)
                if not rec:
                    return await send_message(f"לא נמצא טרייד id={tid}")
                entry = float(rec["entry"])
                sl    = float(rec["sl"])
                lev   = int(rec.get("leverage", 10))
                budget= float(rec.get("budget", 30.0))
                qty, notion, margin = _calc_size(entry, sl, lev, budget, rpct)
                txt = (
                    f"🧮 *Position Size*\n"
                    f"ID: `{tid}` | {rec.get('symbol','?')}\n"
                    f"Risk: {rpct:.2f}% מתוך Budget={_fmt_usd(budget)}\n"
                    f"Entry={entry:.6f}  SL={sl:.6f}  Lev=x{lev}\n"
                    f"*Qty*={qty:.6f}\n"
                    f"Notional≈{_fmt_usd(notion)} | Margin≈{_fmt_usd(margin)}"
                )
                return await send_message(txt)
            except Exception as e:
                return await send_message(f"❌ שימוש: /size <trade_id> <risk_pct>\n({e})")

        # ---------- AUTO ----------
        if text.startswith("/auto_on"):
            os.environ["TRADE_AUTO










