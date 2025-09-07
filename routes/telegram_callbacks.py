# routes/telegram_callbacks.py
from __future__ import annotations
import os, json, re, time, logging
from typing import Any, Dict, Optional, Tuple

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from telegram import Update

from utils.telegram_notifier import handle_callback_action
from utils.security import verify_hmac, idem_seen
from utils.risk import suggest_risk
from utils.binance_client import (
    place_tp_ladder, set_breakeven_stop,
    futures_create_order, set_leverage,
    futures_mark_price, get_symbol_filters, modify_stop_loss
)

logger = logging.getLogger("algogpt.tg_callbacks")
router = APIRouter(prefix="/telegram/callbacks", tags=["TelegramCallbacks"])

# ===== ENV =====
_TP_LADDER_COOLDOWN = int(os.getenv("TP_LADDER_COOLDOWN_SEC", "60"))
_TP_LADDER_ON_APPROVE = os.getenv("TP_LADDER_ON_APPROVE", "1").lower() in ("1","true","yes","on")
_AUTO_OPEN_ON_APPROVE = os.getenv("AUTO_OPEN_ON_APPROVE", "1").lower() in ("1","true","yes","on")
_TELEGRAM_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
_HMAC_ENABLED = bool(os.getenv("WEBHOOK_HMAC_SECRET", "").strip())
_X_SIG_HDRS = ("x-algogpt-signature", "X-Algogpt-Signature", "X-Hub-Signature-256")
_X_IDEM = "X-Idempotency-Key"

_LADDER_LAST: Dict[str, float] = {}

def _cooldown_ok(symbol: str) -> bool:
    t = time.time()
    last = _LADDER_LAST.get(symbol, 0.0)
    if t - last >= _TP_LADDER_COOLDOWN:
        _LADDER_LAST[symbol] = t
        return True
    return False

_APPROVE_HINTS = ("approve", "approved", "✅", "אשר", "אושר", "מאושר", "לאשר")
_SIDE_HINTS = {
    "long":"LONG","buy":"LONG","לונג":"LONG","קנייה":"LONG","קניה":"LONG",
    "short":"SHORT","sell":"SHORT","שורט":"SHORT","מכירה":"SHORT"
}
_SYMBOL_RE = re.compile(r"\b([A-Z0-9]{3,20}(?:USDT|USDC|BUSD|FDUSD|TUSD))\b")

def _detect_approved(update: Update, result: Any) -> bool:
    if isinstance(result, dict):
        if result.get("approved") is True: return True
        if str(result.get("action","")).lower() in ("approve","approved"): return True
    try:
        data = update.callback_query.data if update.callback_query else None
        if data:
            try:
                dj = json.loads(data)
                act = str(dj.get("action","")).lower()
                if act in ("approve","approved"): return True
            except Exception:
                if any(h in str(data).lower() for h in _APPROVE_HINTS): return True
    except Exception:
        pass
    text = update.callback_query.message.text if (update and update.callback_query and update.callback_query.message) else ""
    return bool(text and any(h in text.lower() for h in _APPROVE_HINTS))

def _extract_symbol_side(update: Update, result: Any) -> Tuple[Optional[str], Optional[str]]:
    # JSON מה-handler
    if isinstance(result, dict):
        sym = result.get("symbol") or result.get("sym") or result.get("ticker")
        side = result.get("side")
        if isinstance(sym,str) and isinstance(side,str) and sym.strip() and side.strip():
            sd = side.strip().upper()
            if sd in ("LONG","SHORT"): return sym.strip().upper(), sd
            if sd in ("BUY","SELL"):    return sym.strip().upper(), ("LONG" if sd=="BUY" else "SHORT")
    # מהטקסט של ההודעה
    text = update.callback_query.message.text if (update and update.callback_query and update.callback_query.message) else ""
    if text:
        m = _SYMBOL_RE.search(text.upper()); sym = m.group(1) if m else None
        side = None; low = text.lower()
        for k,v in _SIDE_HINTS.items():
            if k in low: side = v; break
        if sym and side: return sym, side
    # מתוך data של הכפתור
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
            except Exception:
                pass
    except Exception:
        pass
    return None, None

def _be_immediate_allowed() -> bool:
    return os.getenv("TP_BE_ONLY_AFTER_TP1","1").lower() in ("0","false","no")

def _be_offset_bps_default() -> float:
    try: return float(os.getenv("TP_BE_OFFSET_BPS","5"))
    except: return 5.0

def _verify_secret(req: Request) -> bool:
    if not _TELEGRAM_SECRET: return True
    tok = req.headers.get("x-telegram-bot-api-secret-token") or req.headers.get("X-Telegram-Bot-Api-Secret-Token")
    return str(tok or "").strip() == _TELEGRAM_SECRET

def _verify_optional_hmac(req: Request, body: bytes) -> bool:
    if not _HMAC_ENABLED:
        return True
    header_val = None
    for h in _X_SIG_HDRS:
        if h in req.headers:
            header_val = req.headers[h]
            break
    if not header_val:
        return True  # אם תרצה להחמיר → החזר False
    sig_hex = header_val.split("=",1)[1] if "=" in header_val else header_val
    return verify_hmac(sig_hex, body)

def _side_to_exchange(side: str) -> Tuple[str,str]:
    s = (side or "").upper()
    if s in ("LONG","BUY"):  return "BUY","LONG"
    if s in ("SHORT","SELL"): return "SELL","SHORT"
    return "BUY","LONG"

def _quantize_qty(symbol: str, price: float, qty_guess: float) -> float:
    f = get_symbol_filters(symbol) or {}
    step = float(f.get("stepSize") or 0.001)
    min_notional = float(f.get("minNotional") or 5.0)
    qty = max(qty_guess, min_notional / max(price, 1e-12))
    if step <= 0: step = 0.001
    steps = int(qty / step)
    return max(step, steps * step)

def _open_after_approve(symbol: str, side: str, entry_hint: Optional[float]=None, sl_price: Optional[float]=None,
                        leverage_hint: Optional[int]=None, budget_usd_hint: Optional[float]=None) -> Dict[str, Any]:
    su = symbol.upper()
    ex_side, pos_side = _side_to_exchange(side)
    price = futures_mark_price(su) or float(entry_hint or 0.0) or 0.0

    # Risk suggest (עם נפילות עדינות)
    try:
        r = suggest_risk(symbol=su, entry=price or float(entry_hint or 0.0), sl=float(sl_price or 0.0),
                         budget_usd=budget_usd_hint, leverage=leverage_hint)
        leverage = int(r.get("leverage") or leverage_hint or 10)
        budget_usd = float(r.get("budget_usd") or budget_usd_hint or 50.0)
        qty_risk = float(r.get("quantity") or 0.0)
    except Exception:
        leverage = int(leverage_hint or 10)
        budget_usd = float(budget_usd_hint or 50.0)
        px = price if price > 0 else float(entry_hint or 0.0)
        qty_risk = (budget_usd * leverage) / max(px, 1e-12)

    px_ref = price if price > 0 else float(entry_hint or 0.0) or 1.0
    qty = _quantize_qty(su, px_ref, qty_risk)

    lev_resp = set_leverage(su, leverage)
    order = futures_create_order(symbol=su, side=ex_side, type="MARKET", quantity=str(qty))

    sl_resp = None
    if sl_price and sl_price > 0:
        sl_resp = modify_stop_loss(su, float(sl_price), position_side=pos_side)

    return {
        "leverage_set": lev_resp,
        "market_order": order,
        "stop_loss": sl_resp,
        "qty": qty,
        "price_ref": px_ref,
        "pos_side": pos_side,
    }

@router.post("/")
async def telegram_callback_webhook(request: Request):
    raw = await request.body()

    if not _verify_secret(request):
        return JSONResponse(status_code=403, content={"ok": False, "error": "forbidden"})

    if not _verify_optional_hmac(request, raw):
        return JSONResponse(status_code=403, content={"ok": False, "error": "forbidden"})

    # ✅ מניעת דאבל-קליק
    idem = request.headers.get(_X_IDEM)
    if idem and idem_seen(f"tgcb:{idem}"):
        return JSONResponse(content={"ok": True, "duplicate": True})

    try:
        payload = json.loads(raw) if raw else {}
        update = Update.de_json(payload, None)
        result = await handle_callback_action(update)

        approved = _detect_approved(update, result)
        ladder = None; be_res = None; cooldown_wait = None; opened = None

        if approved:
            # חילוץ פרטים
            symbol, side = _extract_symbol_side(update, result)
            entry = None
            tp_targets = None
            sl_price = None
            leverage_hint = None
            budget_usd_hint = None

            if isinstance(result, dict):
                entry = result.get("entry") or result.get("price")
                sl_price = result.get("sl") or result.get("stop") or result.get("stop_loss")
                tp_targets = result.get("targets") or result.get("tps")
                leverage_hint = result.get("leverage")
                budget_usd_hint = result.get("budget_usd")

            # פתיחה אוטומטית אחרי אישור (אם מופעל ב-ENV)
            if _AUTO_OPEN_ON_APPROVE and symbol and side:
                try:
                    opened = _open_after_approve(
                        symbol, side, entry_hint=entry, sl_price=sl_price,
                        leverage_hint=leverage_hint, budget_usd_hint=budget_usd_hint
                    )
                except Exception as e:
                    logger.warning("open_after_approve failed: %s", e)
                    opened = {"ok": False, "error": str(e)}

            # TP Ladder + BE (עם קירור)
            if _TP_LADDER_ON_APPROVE and symbol and side:
                if _cooldown_ok(symbol):
                    try:
                        if isinstance(tp_targets, (list, tuple)) and len(tp_targets) > 0:
                            ladder = place_tp_ladder(symbol, targets_prices=[float(x) for x in tp_targets], position_side=side)
                        else:
                            ladder = place_tp_ladder(symbol, position_side=side)
                    except Exception as e:
                        logger.warning("TP ladder failed: %s", e)
                        ladder = {"ok": False, "error": str(e)}
                    if _be_immediate_allowed():
                        try:
                            be_res = set_breakeven_stop(symbol, offset_bps=_be_offset_bps_default())
                        except Exception as e:
                            logger.warning("BE set failed: %s", e)
                            be_res = {"ok": False, "error": str(e)}
                else:
                    cooldown_wait = max(0, int(_TP_LADDER_COOLDOWN - (time.time() - _LADDER_LAST.get(symbol, 0.0))))

        return JSONResponse(content={
            "ok": True,
            "approved": approved,
            "result": result,
            "opened": opened,
            "ladder": ladder,
            "be": be_res,
            "cooldown_wait": cooldown_wait
        })
    except Exception as e:
        logger.exception("telegram_callback_webhook failed")
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})











