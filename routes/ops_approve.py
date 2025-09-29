# routes/ops_approve.py
from __future__ import annotations
import os, json, time, hmac, hashlib, secrets, logging, math, re
from typing import Any, Dict, Optional
from fastapi import APIRouter, HTTPException, Body, Query, Request
from fastapi.responses import HTMLResponse
import httpx

logger = logging.getLogger("algogpt.ops_approve")
router = APIRouter(tags=["ops-approval"])

# -------- Optional Redis ----------
try:
    import redis.asyncio as aioredis  # type: ignore
except Exception:
    aioredis = None  # type: ignore

NS                   = os.getenv("REDIS_NAMESPACE", "ops-supervisor-web").strip() or "ops-supervisor-web"
REDIS_URL            = os.getenv("REDIS_URL", "")
PUBLIC_HOST          = (os.getenv("PUBLIC_HOST") or os.getenv("WEBHOOK_HOST") or "").strip()
HMAC_SECRET          = (os.getenv("WEBHOOK_HMAC_SECRET") or os.getenv("OPS_SIGN_SECRET") or "").strip()
ADMIN_CHAT_ID        = os.getenv("TELEGRAM_CHAT_ID") or os.getenv("ADMIN_CHAT_ID")
BOT_TOKEN            = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
API_BEARER_TOKEN     = (os.getenv("API_BEARER_TOKEN") or os.getenv("API_TOKEN") or "").strip()
TICKET_TTL_SEC       = int(os.getenv("OPS_TICKET_TTL_SEC", "1800"))  # 👈 ודא ש-ENV קיים
ETA_SMART_ENABLE     = (os.getenv("ETA_SMART_ENABLE","0").lower() in ("1","true","yes","on"))
ETA_VELOCITY_WINDOW  = int(os.getenv("ETA_VELOCITY_WINDOW","30"))
DEFAULT_INTERVAL     = os.getenv("DEFAULT_INTERVAL","15m")

# פרסר דגלים (אופציונלי)
try:
    from routes.ops_flags import apply_note_flags  # type: ignore
except Exception:
    def apply_note_flags(note, ticket): return ticket

def KEY_TICKET(tid: str) -> str:
    return f"{NS}:ticket:{tid}"

async def _redis():
    if not (aioredis and REDIS_URL):
        raise RuntimeError("redis_unavailable")
    return aioredis.from_url(REDIS_URL, decode_responses=True)

# -------- ConfirmStore fallback ----------
try:
    from utils.trade_executor import ConfirmStore  # type: ignore
except Exception:
    try:
        from app.trade_executor import ConfirmStore  # type: ignore
    except Exception:
        from main import ConfirmStore  # type: ignore

# -------- Small utils ----------
def _md_html(s: str) -> str:
    return str(s).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

def _html(msg: str) -> HTMLResponse:
    return HTMLResponse(
        "<!doctype html><meta charset='utf-8'>"
        "<body style='font-family:sans-serif;max-width:560px;margin:3rem auto;line-height:1.5'>"
        f"<h2 style='margin:0 0 .5rem 0'>{msg}</h2>"
        "<p style='color:#666'>אפשר לחזור חזרה לטלגרם.</p>"
        "</body>"
    )

def _expired(ts: float, ttl_sec: int = TICKET_TTL_SEC) -> bool:
    try:
        return (time.time() - float(ts)) > ttl_sec
    except Exception:
        return True

def _sign_hex(secret_hex_or_text: str, payload: bytes) -> str:
    key = bytes.fromhex(secret_hex_or_text) if len(secret_hex_or_text)==64 else secret_hex_or_text.encode("utf-8")
    return hmac.new(key, payload, hashlib.sha256).hexdigest()

# -------- Mode parsing ----------
_MODE_RX = re.compile(r"\[mode:\s*(MARKET|HYBRID|AUTO)\s*\]", flags=re.I)
def _parse_mode(note: Optional[str]) -> Optional[str]:
    if not note: return None
    m = _MODE_RX.search(str(note))
    return m.group(1).upper() if m else None

# -------- Telegram --------
async def _send_telegram_html(text: str, approve_url: Optional[str] = None, reject_url: Optional[str] = None) -> Dict[str, Any]:
    if not BOT_TOKEN or not ADMIN_CHAT_ID:
        return {"ok": False, "skipped": True}
    payload: Dict[str, Any] = {
        "chat_id": int(ADMIN_CHAT_ID) if str(ADMIN_CHAT_ID).isdigit() else ADMIN_CHAT_ID,
        "text": text, "parse_mode": "HTML", "disable_web_page_preview": True,
    }
    if approve_url or reject_url:
        payload["reply_markup"] = {"inline_keyboard":[[
            {"text":"✅ Approve","url":approve_url or PUBLIC_HOST or "https://example.com"},
            {"text":"❌ Reject","url":reject_url or PUBLIC_HOST or "https://example.com"},
        ]]}
    try:
        async with httpx.AsyncClient(timeout=12.0) as cli:
            r = await cli.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json=payload)
        try:
            data = r.json()
        except Exception:
            data = {"ok": False, "status": r.status_code, "text": r.text}
        return data
    except Exception as e:
        return {"ok": False, "error": str(e)}

# -------- Execution backends ----------
async def _execute_trade(ticket: Dict[str, Any]) -> Dict[str, Any]:
    # ניסיון ראשון: אקזקיוטור פנימי אם קיים
    try:
        from utils.trade_executor import place_futures_market  # type: ignore
        return await place_futures_market(ticket)
    except Exception:
        pass
    # נפילה ל-Binance SDK אם אין אקזקיוטור
    try:
        from binance.client import Client  # type: ignore
    except Exception as e:
        logger.error("binance import failed: %s", e)
        return {"ok": False, "error": "binance_client_import_failed", "detail": str(e)}
    try:
        api_key = os.getenv("BINANCE_API_KEY","").strip()
        api_sec = os.getenv("BINANCE_API_SECRET","").strip()
        if not api_key or not api_sec:
            return {"ok": False, "error": "binance_keys_missing"}
        client = Client(api_key, api_sec)
        symbol   = str(ticket.get("symbol","")).upper()
        side     = str(ticket.get("side","")).upper()
        qty      = float(ticket.get("qty", 0))
        leverage = int(ticket.get("leverage", 1))
        if not(symbol and side and qty > 0 and leverage > 0):
            return {"ok": False, "error": "bad_ticket_params"}
        try:
            client.futures_change_leverage(symbol=symbol, leverage=leverage)
        except Exception as e:
            logger.warning("futures_change_leverage failed: %s", e)
        order = client.futures_create_order(
            symbol=symbol, side=side, type="MARKET", quantity=qty,
            newClientOrderId=f"ALG_{symbol}_{side}_{int(time.time())}"
        )
        return {"ok": True, "exchange": "binance_futures", "order": order}
    except Exception as e:
        logger.error("futures_create_order failed: %s", e)
        return {"ok": False, "error": "order_failed", "detail": str(e)}

def _bool_env(name: str, default: bool=False) -> bool:
    return str(os.getenv(name, "1" if default else "0")).lower() in ("1","true","yes","on")

TP_LADDER_ON_APPROVE = _bool_env("TP_LADDER_ON_APPROVE", False)

async def _execute_trade_armed(ticket: Dict[str, Any]) -> Dict[str, Any]:
    # אקזקיוטור החכם (TP/SL/Ladder/Reduce-Only וכו')
    try:
        try:
            from utils.trade_executor import execute_trade_live  # type: ignore
        except Exception:
            from app.trade_executor import execute_trade_live  # type: ignore
    except Exception as e:
        logger.error("execute_trade_live missing: %s", e)
        return {"ok": False, "error": "execute_trade_live_missing", "detail": str(e)}

    symbol   = str(ticket.get("symbol","")).upper()
    side     = str(ticket.get("side","")).upper()
    qty      = float(ticket.get("qty") or 0)
    leverage = int(ticket.get("leverage") or 0)
    pos_side = str(ticket.get("position_side") or "BOTH").upper()

    tps_raw = [ticket.get("tp1"), ticket.get("tp2"), ticket.get("tp3")]
    tp_targets = [float(x) for x in tps_raw if x is not None and str(x) not in ("0","0.0") and float(x) > 0]
    sl_targets = [float(ticket.get("sl"))] if (ticket.get("sl") not in (None, 0, "0", "0.0")) else None

    if not(symbol and side in ("BUY","SELL") and qty > 0 and leverage > 0):
        return {"ok": False, "error": "bad_ticket_params"}

    try:
        res = await execute_trade_live(
            symbol=symbol,
            side=side,
            budget=None,
            leverage=leverage,
            dry_run=False,
            quantity=qty,
            entry=None,
            tp_targets=tp_targets or None,
            sl_targets=sl_targets or None,
            tp_splits=ticket.get("tp_splits"),
            sl_splits=None,
            confirm_first=False,
            telegram_chat_id=int(os.getenv("TELEGRAM_CHAT_ID") or 0),
            position_side=pos_side,
            reduce_only=bool(ticket.get("reduce_only", False)),
            tp_kind=ticket.get("tp_kind"),   # מהדגלים
            sl_kind=ticket.get("sl_kind"),
            entry_kind=ticket.get("entry_kind"),
            entry_offset=ticket.get("entry_offset"),
            tp_offset=ticket.get("tp_offset"),
            sl_offset=ticket.get("sl_offset"),
        )
        return res
    except Exception as e:
        logger.error("armed_execute failed: %s", e)
        return {"ok": False, "error": "armed_execute_failed", "detail": str(e)}

# -------- Smart ETA (optional) --------
def _calc_velocity_per_min(symbol: str, interval: str, window_min: int) -> Optional[float]:
    try:
        from utils.get_klines import get_klines_sync  # type: ignore
        m = {"1m":1, "3m":3, "5m":5, "15m":15, "30m":30, "1h":60}.get(interval, 15)
        n = max(10, math.ceil(window_min / m) + 5)
        kl = get_klines_sync(symbol, interval=interval, limit=n) or []
        closes = [float(x[4]) for x in kl if len(x) >= 5]
        if len(closes) < 2:
            return None
        deltas = [abs(closes[i] - closes[i-1]) for i in range(1, len(closes))]
        avg_per_candle = sum(deltas) / len(deltas)
        per_min = avg_per_candle / m
        return per_min if per_min > 0 else None
    except Exception as e:
        logger.warning("velocity_calc_failed: %s", e)
        return None

def _smart_etas(symbol: str, side: str, price_now: Optional[float], tp1=None, tp2=None, tp3=None,
                interval: str = DEFAULT_INTERVAL, window_min: int = ETA_VELOCITY_WINDOW) -> Dict[str, Optional[int]]:
    vpm = _calc_velocity_per_min(symbol, interval, window_min)
    if not (price_now and vpm and vpm > 0):
        return {"eta_tp1_min": None, "eta_tp2_min": None, "eta_tp3_min": None}
    def _eta(tgt):
        if tgt is None: return None
        dist = abs(float(tgt) - float(price_now))
        return int(math.ceil(dist / vpm)) if vpm > 0 else None
    return {
        "eta_tp1_min": _eta(tp1),
        "eta_tp2_min": _eta(tp2),
        "eta_tp3_min": _eta(tp3),
    }

# -------- Storage abstraction --------
import json as _json
async def _load_ticket(tid: str):
    if aioredis and REDIS_URL:
        try:
            r = await _redis()
            raw = await r.get(f"{NS}:ticket:{tid}")
            if raw:
                rec = _json.loads(raw)
                from time import time as _now
                if (_now() - float(rec.get("ts", 0))) <= TICKET_TTL_SEC:
                    return rec.get("req") or rec, "redis"
        except Exception as e:
            logger.warning("redis_load_failed: %s", e)
    try:
        for it in (ConfirmStore.pending() or []):
            if str(it.get("ticket_id")) == str(tid):
                return it.get("req") or it, "confirmstore"
    except Exception as e:
        logger.warning("confirmstore_load_failed: %s", e)
    return None, "none"

async def _delete_ticket(tid: str, source: str) -> None:
    if source == "redis" and aioredis and REDIS_URL:
        try:
            r = await _redis(); await r.delete(f"{NS}:ticket:{tid}"); return
        except Exception as e:
            logger.warning("redis_delete_failed: %s", e)
    try:
        ConfirmStore.decide(tid, approved=False)
    except Exception:
        pass

# -------------------- API --------------------
@router.post("/ops/ticket", summary="Create approval ticket (Redis + ConfirmStore) – sends Telegram")
async def create_ticket(
    payload: Dict[str, Any] = Body(..., description="symbol, side, qty, leverage, optional: TP/SL/ETAs/probs/note/position_side/budget/expiry_ts"),
):
    symbol = (payload.get("symbol") or "").upper().strip()
    side   = (payload.get("side") or "").upper().strip()
    qty    = float(payload.get("qty") or payload.get("quantity") or 0)
    lev    = int(payload.get("leverage") or payload.get("lev") or 0)
    note   = payload.get("note") or ""
    position_side = (payload.get("position_side") or "BOTH").upper()
    budget = float(payload.get("budget") or payload.get("budget_usd") or 0.0)

    if not (symbol and side and qty > 0 and lev > 0):
        raise HTTPException(status_code=422, detail="Missing/invalid fields (symbol/side/qty/leverage)")

    tid = payload.get("ticket_id") or f"T_{secrets.token_hex(4)}"

    # Smart ETAs
    if ETA_SMART_ENABLE and (payload.get("tp1") or payload.get("tp2") or payload.get("tp3")):
        price_now = None
        try:
            from utils.binance_client import get_price  # type: ignore
            price_now = get_price(symbol)
        except Exception:
            price_now = None
        etas = _smart_etas(symbol, side, price_now, payload.get("tp1"), payload.get("tp2"), payload.get("tp3"))
        for k,v in etas.items():
            payload.setdefault(k, v)

    # Build req body
    req_body: Dict[str, Any] = {
        "ticket_id": tid, "symbol": symbol, "side": side, "qty": qty,
        "leverage": lev, "position_side": position_side, "budget": budget, "note": note,
        "score": payload.get("score"),
        "eta_open_min": payload.get("eta_open_min"),
        "tp1": payload.get("tp1"), "tp2": payload.get("tp2"), "tp3": payload.get("tp3"),
        "eta_tp1_min": payload.get("eta_tp1_min"), "eta_tp2_min": payload.get("eta_tp2_min"), "eta_tp3_min": payload.get("eta_tp3_min"),
        "sl": payload.get("sl"),
        "prob_overall_pct": payload.get("prob_overall_pct"),
        "prob_tp1_pct": payload.get("prob_tp1_pct"),
        "prob_tp2_pct": payload.get("prob_tp2_pct"),
        "prob_tp3_pct": payload.get("prob_tp3_pct"),
        "expiry_ts": payload.get("expiry_ts"),
    }

    # 👇 העשרה מתוך הדגלים ב-note (לא חובה)
    req_body = apply_note_flags(note, req_body)

    # 👇 אכיפה רכה של RR_MIN אם קיים בדגלים או ENV (מסמן במקום לחסום קשיח)
    try:
        rr_min_flag = float(req_body.get("rr_min") or 0.0)
        rr_env_lo   = float(os.getenv("APPROVAL_RR_MIN", "0") or "0")
        rr_min_eff  = max(rr_min_flag, rr_env_lo)
        if rr_min_eff > 0 and req_body.get("sl"):
            from utils.binance_client import get_price  # type: ignore
            current = float(get_price(symbol) or 0)
            tp1 = float(req_body.get("tp1") or 0)
            sl  = float(req_body.get("sl") or 0)
            rr  = None
            if side == "BUY" and current > 0 and tp1 > 0 and sl > 0:
                reward = abs(tp1 - current); risk = abs(current - sl); rr = (reward / risk) if risk > 0 else None
            elif side == "SELL" and current > 0 and tp1 > 0 and sl > 0:
                reward = abs(current - tp1); risk = abs(sl - current); rr = (reward / risk) if risk > 0 else None
            if rr is not None and rr < rr_min_eff:
                req_body["blocked_by_rr_min"] = True
    except Exception:
        pass

    # Persist
    try:
        ConfirmStore.create(dict(req_body))
    except Exception:
        pass
    if aioredis and REDIS_URL:
        try:
            r = await _redis()
            rec = {"ts": time.time(), "req": req_body, "note": note}
            await r.setex(f"{NS}:ticket:{tid}", TICKET_TTL_SEC, json.dumps(rec, ensure_ascii=False, separators=(",", ":")))
        except Exception as e:
            logger.warning("redis_set_failed: %s", e)

    approve_url = f"{PUBLIC_HOST.rstrip('/')}/ops/approve?ticket_id={tid}" if PUBLIC_HOST else ""
    reject_url  = f"{PUBLIC_HOST.rstrip('/')}/ops/reject?ticket_id={tid}"  if PUBLIC_HOST else ""

    # Telegram
    lines = []
    lines.append("⚠️ <b>Approval Needed</b>")
    lines.append(f"• Ticket: <code>{_md_html(tid)}</code>")
    lines.append(f"• {_md_html(symbol)} {_md_html(side)} qty=<code>{qty}</code> lev=<code>{lev}</code>")
    if req_body.get("score") is not None:
        lines.append(f"• Score: <code>{req_body['score']}</code>")
    if req_body.get("eta_open_min") is not None:
        lines.append(f"• ETA Open: <code>{req_body['eta_open_min']}m</code>")
    for i in (1,2,3):
        tpv = req_body.get(f"tp{i}")
        etv = req_body.get(f"eta_tp{i}_min")
        prv = req_body.get(f"prob_tp{i}_pct")
        if tpv is not None:
            row = f"• TP{i}: <code>{tpv}</code>"
            if etv is not None: row += f"  ETA:<code>{etv}m</code>"
            if prv is not None: row += f"  P(s):<code>{prv}%</code>"
            lines.append(row)
    if req_body.get("sl") is not None:
        lines.append(f"• SL: <code>{req_body['sl']}</code>")
    mode = _parse_mode(note)
    if mode:
        lines.append(f"• Mode: <code>{mode}</code>")
    # אם דגלים עיקריים קיימים – נציג בקצרה
    if req_body.get("tp_kind"):
        lines.append(f"• TP Kind: <code>{req_body['tp_kind']}</code>")
    if req_body.get("tp_splits"):
        lines.append(f"• TP Splits: <code>{req_body['tp_splits']}</code>")
    if req_body.get("sl_kind"):
        lines.append(f"• SL Kind: <code>{req_body['sl_kind']}</code>")
    if req_body.get("entry_kind"):
        lines.append(f"• Entry: <code>{req_body['entry_kind']}</code>")
    if req_body.get("reduce_only"):
        lines.append(f"• Reduce Only: <code>True</code>")
    if req_body.get("blocked_by_rr_min"):
        lines.append("• RR Check: <code>Below RR_MIN (manual review)</code>")

    if req_body.get("prob_overall_pct") is not None:
        lines.append(f"• Success %: <code>{req_body['prob_overall_pct']}%</code>")
    if req_body.get("expiry_ts") is not None:
        lines.append(f"• Expires: <code>{req_body['expiry_ts']}</code>")
    if note:
        lines.append(f"• Note: {_md_html(note)}")
    lines.append("— — —")
    lines.append("בחר:")

    pretty = "\n".join(lines)
    tg_resp = await _send_telegram_html(pretty, approve_url=approve_url or None, reject_url=reject_url or None)

    return {
        "ok": True,
        "ticket_id": tid,
        "approve_url": approve_url,
        "reject_url": reject_url,
        "telegram_result": tg_resp
    }

def _decide_flow_by_mode(ticket: Dict[str, Any]) -> str:
    mode = _parse_mode(ticket.get("note"))
    if mode in ("MARKET", "HYBRID", "AUTO"):
        return mode
    return "HYBRID" if str(os.getenv("TP_LADDER_ON_APPROVE","0")).lower() in ("1","true","yes","on") else "MARKET"

@router.get("/ops/approve", summary="Approve ticket (supports ticket_id) -> executes trade")
async def approve(ticket_id: str = Query(..., description="ticket_id")):
    ticket, source = await _load_ticket(ticket_id)
    if not ticket:
        return _html("⚠️ קישור שגוי או שפג תוקף האישור.")

    flow = _decide_flow_by_mode(ticket)
    if flow == "MARKET":
        exec_res = await _execute_trade(ticket)
    elif flow == "HYBRID":
        exec_res = await _execute_trade_armed(ticket)
    else:  # AUTO
        if any(ticket.get(k) for k in ("tp1","tp2","tp3","sl")):
            exec_res = await _execute_trade_armed(ticket)
        else:
            exec_res = await _execute_trade(ticket)

    ok = bool(exec_res.get("ok"))

    try:
        sym, side, qty = ticket.get("symbol",""), ticket.get("side",""), ticket.get("qty","")
        if ok:
            txt = (
                f"✅ <b>Approved</b>\n"
                f"• Ticket: <code>{_md_html(ticket_id)}</code>\n"
                f"• {_md_html(sym)} {_md_html(side)} qty={qty}\n"
                f"• Flow: <code>{flow}</code>\n"
                "— — —\nבוצע והועבר לניהול."
            )
        else:
            txt = (
                f"⚠️ <b>Approve Failed</b>\n"
                f"• Ticket: <code>{_md_html(ticket_id)}</code>\n"
                f"• {_md_html(sym)} {_md_html(side)} qty={qty}\n"
                f"• Flow: <code>{flow}</code>\n"
                f"— — —\nשגיאה: <code>{_md_html(json.dumps(exec_res, ensure_ascii=False))}</code>"
            )
        await _send_telegram_html(txt)
    except Exception:
        pass

    try:
        ConfirmStore.decide(ticket_id, approved=ok)
    except Exception:
        pass
    await _delete_ticket(ticket_id, source)

    if ok:
        return _html("✅ אושר — הוזמן ונכנס לניהול דינמי.")
    else:
        return _html("⚠️ שגיאה בביצוע — ראה פירוט בטלגרם/לוגים.")

@router.get("/ops/approve-link", summary="Approve legacy link (?id=...)")
async def approve_link(id: str = Query(..., description="ticket_id")):
    return await approve(ticket_id=id)

@router.get("/ops/reject", summary="Reject ticket (delete) – supports ticket_id")
async def reject(ticket_id: str = Query(..., description="ticket_id")):
    ticket, source = await _load_ticket(ticket_id)
    await _delete_ticket(ticket_id, source)
    try:
        await _send_telegram_html(
            f"❌ <b>Rejected</b>\n• Ticket: <code>{_md_html(ticket_id)}</code>\n— — —\nNo action was taken."
        )
    except Exception:
        pass
    try:
        ConfirmStore.decide(ticket_id, approved=False)
    except Exception:
        pass
    return _html("❌ נדחה. לא בוצעה פעולה.")

@router.post("/ops/approve/signed", summary="Internal signed approve endpoint (executes trade)")
async def approve_signed(request: Request):
    if not HMAC_SECRET:
        raise HTTPException(status_code=500, detail="HMAC secret not set")
    raw = await request.body()
    got = request.headers.get("X-Signature", "") or ""
    want = _sign_hex(HMAC_SECRET, raw)
    if not hmac.compare_digest(got, want):
        raise HTTPException(status_code=401, detail="Bad signature")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    flow = _decide_flow_by_mode(payload)
    if flow == "MARKET":
        exec_res = await _execute_trade(payload)
    elif flow == "HYBRID":
        exec_res = await _execute_trade_armed(payload)
    else:
        if any(payload.get(k) for k in ("tp1","tp2","tp3","sl")):
            exec_res = await _execute_trade_armed(payload)
        else:
            exec_res = await _execute_trade(payload)

    ok = bool(exec_res.get("ok"))
    if not ok:
        raise HTTPException(status_code=502, detail={"execute_error": exec_res})
    return {"ok": True, "ticket_id": payload.get("ticket_id"), "executed": True, "flow": flow, "internal_execute": exec_res}





