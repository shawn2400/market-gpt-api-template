# routes/telegram_callbacks.py
from __future__ import annotations
import os, json, re, time, logging, hmac, hashlib
from typing import Any, Dict, Optional, Tuple
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from telegram import Update

from utils.telegram_notifier import handle_callback_action
from utils.binance_client import place_tp_ladder, set_breakeven_stop

logger = logging.getLogger("algogpt.tg_callbacks")
router = APIRouter(prefix="/telegram/callbacks", tags=["TelegramCallbacks"])

_TP_LADDER_COOLDOWN = int(os.getenv("TP_LADDER_COOLDOWN_SEC", "60"))
_TP_LADDER_ON_APPROVE = str(os.getenv("TP_LADDER_ON_APPROVE", "1")).lower() in ("1","true","yes","on")
_TELEGRAM_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
_HMAC_SECRET = os.getenv("WEBHOOK_HMAC_SECRET", "").encode("utf-8")

_LADDER_LAST: Dict[str, float] = {}

def _cooldown_ok(symbol: str) -> bool:
    t = time.time()
    last = _LADDER_LAST.get(symbol, 0.0)
    if t - last >= _TP_LADDER_COOLDOWN:
        _LADDER_LAST[symbol] = t
        return True
    return False

_APPROVE_HINTS = ("approve", "approved", "✅", "אשר", "אושר", "מאושר", "לאשר")
_SIDE_HINTS = {"long":"LONG","buy":"LONG","לונג":"LONG","קנייה":"LONG","short":"SHORT","sell":"SHORT","שורט":"SHORT","מכירה":"SHORT"}

def _detect_approved(update: Update, result: Any) -> bool:
    if isinstance(result, dict):
        if result.get("approved") is True: return True
        if str(result.get("action","")).lower() in ("approve","approved"): return True
    try:
        data = update.callback_query.data if update.callback_query else None
        if data:
            try:
                dj = json.loads(data); act = str(dj.get("action","")).lower()
                if act in ("approve","approved"): return True
            except Exception:
                if any(h in str(data).lower() for h in _APPROVE_HINTS): return True
    except Exception: pass
    text = update.callback_query.message.text if (update and update.callback_query and update.callback_query.message) else ""
    return bool(text and any(h in text.lower() for h in _APPROVE_HINTS))

def _extract_symbol_side(update: Update, result: Any) -> Tuple[Optional[str], Optional[str]]:
    if isinstance(result, dict):
        sym = result.get("symbol") or result.get("sym") or result.get("ticker")
        side = result.get("side")
        if isinstance(sym,str) and sym.strip() and isinstance(side,str) and side.strip():
            sd = side.strip().upper()
            if sd in ("LONG","SHORT"): return sym.strip().upper(), sd
            if sd in ("BUY","SELL"):    return sym.strip().upper(), ("LONG" if sd=="BUY" else "SHORT")
    text = update.callback_query.message.text if (update and update.callback_query and update.callback_query.message) else ""
    if text:
        m = re.search(r"\b([A-Z]{3,15}USDT)\b", text)
        sym = m.group(1) if m else None
        side = None; low = text.lower()
        for k,v in _SIDE_HINTS.items():
            if k in low: side = v; break
        if sym and side: return sym, side
    try:
        data = update.callback_query.data if update.callback_query else None
        if data:
            try:
                dj = json.loads(data)
                sym = (dj.get("symbol") or dj.get("sym") or dj.get("ticker") or "").strip().upper()
                sd  = (dj.get("side") or dj.get("position") or dj.get("dir") or "").strip().upper()
                if sym and sd:
                    if sd in ("LONG","SHORT"): return sym, sd
                    if sd in ("BUY","SELL"):   return sym, ("LONG" if sd=="BUY" else "SHORT")
            except Exception: pass
    except Exception: pass
    return None, None

def _be_immediate_allowed() -> bool:
    return str(os.getenv("TP_BE_ONLY_AFTER_TP1","1")).lower() in ("0","false","no")

def _be_offset_bps_default() -> float:
    try: return float(os.getenv("TP_BE_OFFSET_BPS","5"))
    except: return 5.0

def _verify_secret(req: Request) -> bool:
    if not _TELEGRAM_SECRET: return True
    tok = req.headers.get("x-telegram-bot-api-secret-token") or req.headers.get("X-Telegram-Bot-Api-Secret-Token")
    return str(tok or "").strip() == _TELEGRAM_SECRET

def _verify_optional_hmac(req: Request, body: bytes) -> bool:
    if not _HMAC_SECRET: return True
    header = req.headers.get("x-algogpt-signature") or req.headers.get("X-Hub-Signature-256")
    if not header: return True
    if "=" in header:
        scheme, sig_hex = header.split("=",1)
        if scheme.lower() != "sha256": return False
    else:
        sig_hex = header
    digest = hmac.new(_HMAC_SECRET, body, digestmod=hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig_hex, digest)

@router.post("/")
async def telegram_callback_webhook(request: Request):
    raw = await request.body()
    if not _verify_secret(request):
        return JSONResponse(status_code=403, content={"ok": False, "error": "forbidden"})
    if not _verify_optional_hmac(request, raw):
        return JSONResponse(status_code=403, content={"ok": False, "error": "forbidden"})
    try:
        payload = json.loads(raw) if raw else {}
        update = Update.de_json(payload, None)
        result = await handle_callback_action(update)

        approved = _detect_approved(update, result)
        ladder = None; be_res = None

        if approved and _TP_LADDER_ON_APPROVE:
            symbol, side = _extract_symbol_side(update, result)
            if symbol and side and _cooldown_ok(symbol):
                try:
                    ladder = place_tp_ladder(symbol)
                except Exception as e:
                    logger.warning("TP ladder failed: %s", e)
                    ladder = {"ok": False, "error": str(e)}
                if _be_immediate_allowed():
                    try:
                        be_res = set_breakeven_stop(symbol, offset_bps=_be_offset_bps_default())
                    except Exception as e:
                        logger.warning("BE set failed: %s", e)
                        be_res = {"ok": False, "error": str(e)}

        return JSONResponse(content={"ok": True, "result": result, "ladder": ladder, "be": be_res})
    except Exception as e:
        logger.exception("telegram_callback_webhook failed")
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})









