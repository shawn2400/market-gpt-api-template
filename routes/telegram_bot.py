# routes/telegram_bot.py
from __future__ import annotations

from fastapi import APIRouter, Request, HTTPException, Depends
from pydantic import BaseModel
from typing import Dict, Any, Optional, List, Tuple
import os, json, asyncio, uuid, time, hashlib
import httpx

from utils.auth import require_api_key
from utils.telegram_api import send_message, edit_message
from utils.trade_models import TradeProposal
from utils.liquidity import estimate_slippage
from utils.trade_validator import validate_proposal
from utils.approvals import preflight_proposal
from utils.runtime_prefs import (
    set_mute, clear_mute, mute_remaining_sec,
    set_near_pct_override, get_near_pct_override,
    set_trade_quiet, TelePrefs
)
from utils.hmac_utils import build_signed_outbound, generate_idempotency_key, sign_payload
from utils.binance_client import futures_mark_price

TPREFS = TelePrefs()

router_public = APIRouter(prefix="/telegram", tags=["Telegram"])
router = APIRouter(prefix="/telegram", tags=["Telegram"], dependencies=[Depends(require_api_key)])

PENDING: Dict[str, Dict[str, Any]] = {}

ALERTS_ACTIVE_URL = os.getenv("ALERTS_ACTIVE_URL", "http://127.0.0.1:8000/alerts/trades/active").strip()
ALERTS_UPDATE_URL = os.getenv("ALERTS_UPDATE_URL", "http://127.0.0.1:8000/alerts/trades/update").strip()
ALERTS_INGEST_URL = os.getenv("ALERTS_INGEST_URL", "http://127.0.0.1:8000/alerts/trade-ingest").strip()

WEBHOOK_HMAC_SECRET = os.getenv("WEBHOOK_HMAC_SECRET", "").strip()
DEFAULT_INTERVAL = os.getenv("DEFAULT_INTERVAL", "15m")
DEFAULT_MARKET = os.getenv("DEFAULT_MARKET", "futures")
TELEGRAM_WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()

# ===== Models =====
class WebhookSet(BaseModel):
    url: str

# ===== Internals =====
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

# ===== API =====
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
        r.raise_for_status()
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
            return await send_message("📋 פקודות זמינות: /propose, /approve, /reject, /summary ...")

        # --- propose ---
        if text.startswith("/propose "):
            try:
                parts = text.split()
                if len(parts) < 11:
                    return await send_message("⚠️ שימוש: /propose <symbol> <interval> <LONG|SHORT> <lev> <entry> <sl> <tp1> <tp2> <tp3> <success_pct>")
                _, symbol, interval, side, lev, entry, sl, tp1, tp2, tp3, succ = parts[:11]
                symbol = symbol.upper()

                nowp = futures_mark_price(symbol) or float(entry)
                tid = uuid.uuid4().hex[:8].upper()
                tp_dict = {
                    "symbol": symbol, "side": side.upper(),
                    "leverage": int(float(lev)), "entry": float(entry),
                    "sl": float(sl), "tp1": float(tp1), "tp2": float(tp2), "tp3": float(tp3),
                    "success_pct": float(succ), "current_price": float(nowp),
                    "budget_usd": float(os.getenv("DEFAULT_BUDGET_USD", "30")),
                }

                v = await validate_proposal(tp_dict, interval=interval, market=DEFAULT_MARKET)
                pre = preflight_proposal({**tp_dict, "interval": interval})
                if not pre["ok"]:
                    return await send_message("❌ ההצעה נדחתה (Preflight)")

                PENDING[tid] = {"tp": tp_dict, "interval": interval}
                txt = (
                    f"📥 *Proposal* #{tid}\n"
                    f"{symbol} {side.upper()} x{int(float(lev))}\n"
                    f"Entry={float(entry):.6f} | SL={float(sl):.6f}\n"
                    f"TP1={float(tp1):.6f} | TP2={float(tp2):.6f} | TP3={float(tp3):.6f}\n"
                    f"Now≈{float(nowp):.6f} | Success≈ {float(succ):.1f}%"
                )
                return await send_message(txt, reply_markup=_mk_main_keyboard(tid))
            except Exception as e:
                return await send_message(f"❌ שגיאה ב-/propose: {e}")

        return await send_message("❓ לא זוהתה פקודה. שלח /help.")

    return {"ok": True}



















