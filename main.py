# main.py
from __future__ import annotations

import os, json, time, hmac, math, re, httpx, hashlib, secrets, logging, traceback, inspect, asyncio
from contextlib import suppress
from typing import Any, Dict, List, Optional, Callable, Tuple
from collections import Counter

from fastapi import FastAPI, Request, HTTPException, Body, Query, APIRouter
from fastapi.responses import JSONResponse, PlainTextResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

# =================================================
# Logging
# =================================================
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("algogpt.main")

# =================================================
# Inline ENV defaults (safe, non-secret)
# =================================================
_inline_env_defaults: Dict[str, str] = {
    "GUARD_SL_GRACE_SEC": "2", "ORD_VERIFY_TIMEOUT_MS": "800", "ORD_CANCEL_STRATEGY": "MINIMAL",
    "SL_MONOTONIC": "1", "BE_BUFFER_USDT": "0.03", "ATR_UPDATE_COOLDOWN_SEC": "20",
    "ATR_MIN_DELTA": "0.02", "COALESCE_WINDOW_MS": "1500", "RETRY_MAX": "3", "RETRY_BASE_MS": "500",
    "RETRY_JITTER": "1", "REST_COOLDOWN_SEC": "6", "TP_MAX_LADDERS": "3", "ENABLE_INDICATOR_EXIT": "1",
    "ADX_MIN": "18", "NO_PROGRESS_TIMEOUT_MIN": "30", "DAILY_LOSS_CAP_USDT": "150", "KILL_ON_CAP": "1",
    "PRICE_PROTECT": "1", "USE_WS": "1", "WS_KEEPALIVE_SEC": "25",
}
for _k, _v in _inline_env_defaults.items():
    os.environ.setdefault(_k, _v)

# =================================================
# Simple in-memory ConfirmStore (fallback)
# =================================================
class ConfirmStore:
    _items: Dict[str, Dict[str, Any]] = {}

    @classmethod
    def create(cls, req: Dict[str, Any]) -> None:
        tid = str(req.get("ticket_id") or f"T_{int(time.time())}_{secrets.token_hex(3)}")
        cls._items[tid] = {"ticket_id": tid, "req": dict(req), "ts": time.time(), "approved": None}
        logger.debug("ConfirmStore.create: %s", tid)

    @classmethod
    def decide(cls, ticket_id: str, approved: bool) -> None:
        it = cls._items.get(str(ticket_id))
        if it:
            it["approved"] = bool(approved)
        logger.debug("ConfirmStore.decide: %s -> %s", ticket_id, approved)

    @classmethod
    def pending(cls) -> List[Dict[str, Any]]:
        return [v for v in cls._items.values() if v.get("approved") is None]

# =================================================
# FastAPI App
# =================================================
app = FastAPI(
    title=os.getenv("APP_TITLE", "AlgoGPT Supervisor"),
    version=os.getenv("APP_VERSION", "1.0.0"),
    docs_url=os.getenv("DOCS_URL", "/docs"),
    redoc_url=os.getenv("REDOC_URL", "/redoc"),
    openapi_url=os.getenv("OPENAPI_URL", "/openapi.json"),
)

# CORS
CORS_ALLOW_ORIGINS = os.getenv("CORS_ALLOW_ORIGINS", "*")
CORS_ALLOW_HEADERS = os.getenv("CORS_ALLOW_HEADERS", "*")
CORS_ALLOW_METHODS = os.getenv("CORS_ALLOW_METHODS", "*")
CORS_ALLOW_CREDENTIALS = os.getenv("CORS_ALLOW_CREDENTIALS", "0").lower() in ("1", "true", "yes", "on")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in CORS_ALLOW_ORIGINS.split(",")] if CORS_ALLOW_ORIGINS else ["*"],
    allow_credentials=CORS_ALLOW_CREDENTIALS,
    allow_methods=[m.strip() for m in CORS_ALLOW_METHODS.split(",")] if CORS_ALLOW_METHODS else ["*"],
    allow_headers=[h.strip() for h in CORS_ALLOW_HEADERS.split(",")] if CORS_ALLOW_HEADERS else ["*"],
)

# =================================================
# Helpers
# =================================================
def _port() -> int:
    try:
        return int(os.getenv("PORT", "10000") or "10000")
    except Exception:
        return 10000

def get_internal_base() -> str:
    internal = (os.getenv("INTERNAL_BASE") or "").strip()
    if internal:
        return internal.rstrip("/")
    return f"http://127.0.0.1:{_port()}"

# =================================================
# OPS APPROVE Router
# =================================================
router = APIRouter(tags=["ops-approval"])

with suppress(Exception):
    from utils.guard_stop import ensure_protective_stop  # type: ignore

def record_approval_created(): ...
def record_approval_approved(): ...
def record_approval_rejected(): ...
with suppress(Exception):
    from routes.metrics import (  # type: ignore
        record_approval_created as _rac,
        record_approval_approved as _raa,
        record_approval_rejected as _rar,
    )
    record_approval_created = _rac
    record_approval_approved = _raa
    record_approval_rejected = _rar

try:
    import redis.asyncio as aioredis  # type: ignore
except Exception:
    aioredis = None  # type: ignore

NS  = os.getenv("REDIS_NAMESPACE", "ops-supervisor-web").strip() or "ops-supervisor-web"
REDIS_URL = os.getenv("REDIS_URL", "").strip()
PUBLIC_HOST = (os.getenv("PUBLIC_HOST") or os.getenv("WEBHOOK_HOST") or "").strip()
HMAC_SECRET = (os.getenv("WEBHOOK_HMAC_SECRET") or os.getenv("OPS_SIGN_SECRET") or "").strip()
ADMIN_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID") or os.getenv("ADMIN_CHAT_ID")
BOT_TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
API_BEARER_TOKEN = (os.getenv("API_BEARER_TOKEN") or os.getenv("API_TOKEN") or "").strip()
TICKET_TTL_SEC = int(os.getenv("OPS_TICKET_TTL_SEC", "1800"))
ETA_SMART_ENABLE = (os.getenv("ETA_SMART_ENABLE","0").lower() in ("1","true","yes","on"))
ETA_VELOCITY_WINDOW = int(os.getenv("ETA_VELOCITY_WINDOW","30"))
DEFAULT_INTERVAL = os.getenv("DEFAULT_INTERVAL","15m")

def _bool_env(name: str, default: bool=False) -> bool:
    return str(os.getenv(name, "1" if default else "0")).lower() in ("1","true","yes","on")

TP_LADDER_ON_APPROVE = _bool_env("TP_LADDER_ON_APPROVE", False)
APPROVAL_FAIL_OPEN_ON_VELOCITY = _bool_env("APPROVAL_FAIL_OPEN_ON_VELOCITY", True)
VELOCITY_LOG_LEVEL = (os.getenv("VELOCITY_LOG_LEVEL","WARNING") or "WARNING").upper()
DEBUG_APPROVE_HTML = _bool_env("DEBUG_APPROVE_HTML", False)
APPROVE_FALLBACK_TO_MARKET = not _bool_env("PROPOSE_BLOCK_ON_FAIL", False)

HEALTH_TP1_ENABLE = _bool_env("HEALTH_TP1_ENABLE", True)
HEALTH_TP1_INTERVAL_SEC = int(os.getenv("HEALTH_TP1_INTERVAL_SEC", "600"))
TP1_TAGS = [t.strip() for t in (os.getenv("TP1_TAGS","") or "").split(",") if t.strip()]
SL_TAGS = [t.strip() for t in (os.getenv("SL_TAGS","SL,STOP,STOP_LOSS,STOP_LOSS_LIMIT,STOP_MARKET") or "").split(",") if t.strip()]

# Order ID helper
try:
    from utils.order_ids import build_client_order_id  # type: ignore
except Exception:
    def _coid_fit_local(s: str, limit: int = 36) -> str:
        if len(s) <= limit:
            return s
        h = hashlib.md5(s.encode("utf-8")).hexdigest()[:6]
        return f"{s[:limit-(len(h)+1)]}_{h}"
    def build_client_order_id(symbol: str, side: str, role: str = "ENTRY", extra: Optional[str] = None) -> str:
        prefix = (os.getenv("ORDER_ID_PREFIX") or "ALG").strip() or "ALG"
        sym = str(symbol).upper()
        sd  = str(side).upper()
        rl  = str(role).upper().replace("@","_")
        ts = str(int(time.time()*1000))
        base = "-".join([prefix, sym, sd, rl, ts] + ([str(extra)] if extra else []))
        return _coid_fit_local(base, 36)

# Position sizing helper
try:
    from app.utils.position_sizing import ensure_final_qty  # type: ignore
except Exception:
    with suppress(Exception):
        from utils.position_sizing import ensure_final_qty  # type: ignore
    if "ensure_final_qty" not in globals():
        def ensure_final_qty(ticket: Dict[str, Any], price: float) -> Dict[str, Any]:
            return ticket

# Price helpers
async def _get_last_price_http(symbol: str) -> Optional[float]:
    sym = symbol.upper()
    timeout = httpx.Timeout(6.0, connect=2.0)
    for url in ("https://fapi.binance.com/fapi/v1/ticker/price", "https://api.binance.com/api/v3/ticker/price"):
        try:
            async with httpx.AsyncClient(timeout=timeout) as cli:
                r = await cli.get(url, params={"symbol": sym})
                if r.status_code == 200:
                    data = r.json()
                    p = float(data.get("price"))
                    if p > 0:
                        return p
        except Exception:
            pass
    return None

def _get_last_price(symbol: str) -> Optional[float]:
    with suppress(Exception):
        from utils.binance_client import get_price  # type: ignore
        p = get_price(symbol)
        if p:
            return float(p)
    try:
        return asyncio.get_event_loop().run_until_complete(_get_last_price_http(symbol))
    except Exception:
        pass
    with suppress(Exception):
        from binance.client import Client  # type: ignore
        api_key = os.getenv("BINANCE_API_KEY","").strip()
        api_sec = os.getenv("BINANCE_API_SECRET","").strip()
        if not api_key or not api_sec:
            return None
        cli = Client(api_key, api_sec)
        info = cli.futures_symbol_ticker(symbol=symbol.upper())
        if info and "price" in info:
            return float(info["price"])
    return None

# HTML helpers
def _md_html(s: str) -> str:
    return str(s).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

def _html(msg: str) -> HTMLResponse:
    return HTMLResponse(
        "<!doctype html><meta charset='utf-8'>"
        "<body style='font-family:sans-serif;max-width:720px;margin:3rem auto;line-height:1.5'>"
        f"<h2 style='margin:0 0 .5rem 0'>{msg}</h2>"
        "<p style='color:#666'>אפשר לחזור חזרה לטלגרם.</p>"
        "</body>"
    )

def _sign_hex(secret_hex_or_text: str, payload: bytes) -> str:
    key = bytes.fromhex(secret_hex_or_text) if len(secret_hex_or_text)==64 else secret_hex_or_text.encode("utf-8")
    return hmac.new(key, payload, hashlib.sha256).hexdigest()

async def _redis():
    if not (aioredis and REDIS_URL):
        return None
    return aioredis.from_url(REDIS_URL, decode_responses=True)

_MODE_RX = re.compile(r"\[mode:\s*(MARKET|HYBRID|AUTO)\s*\]", flags=re.I)
def _parse_mode(note: Optional[str]) -> Optional[str]:
    if not note:
        return None
    m = _MODE_RX.search(str(note))
    return m.group(1).upper() if m else None
def _decide_flow_by_mode(ticket: Dict[str, Any]) -> str:
    mode = _parse_mode(ticket.get("note"))
    if mode in ("MARKET", "HYBRID", "AUTO"):
        return mode
    return "HYBRID" if TP_LADDER_ON_APPROVE else "MARKET"

def _apply_auto_qty_on_ticket(ticket: Dict[str, Any]) -> Dict[str, Any] | None:
    symbol = (ticket.get("symbol") or "").upper()
    price = _get_last_price(symbol)
    if not price or float(price) <= 0:
        return None
    new_ticket = ensure_final_qty(dict(ticket), float(price))
    ps = str(new_ticket.get("position_side") or new_ticket.get("positionSide") or "").upper()
    if ps == "BOTH":
        new_ticket.pop("positionSide", None)
        new_ticket["position_side"] = ""
    return new_ticket

def _require_bearer(request: Request) -> None:
    if not API_BEARER_TOKEN:
        return
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer ") or auth.split(" ", 1)[1].strip() != API_BEARER_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")

def _badge(text: str, color: str) -> str:
    return f"<span style='display:inline-block;padding:.15rem .45rem;border-radius:999px;font-size:.8rem;color:#fff;background:{color}'>{_md_html(text)}</span>"

def _status_badge(status: str) -> str:
    s = (status or "").upper()
    color = "#6b7280"
    if s == "NEW": color = "#3b82f6"
    elif s == "PARTIALLY_FILLED": color = "#f59e0b"
    elif s == "FILLED": color = "#10b981"
    elif s in ("CANCELED","EXPIRED","REJECTED"): color = "#ef4444"
    return _badge(s, color)

def _role_badge(role: str) -> str:
    r = (role or "").upper()
    color = "#6b7280"
    if r.startswith("TP"): color = "#16a34a"
    elif r == "SL": color = "#dc2626"
    elif r == "ENTRY": color = "#3b82f6"
    elif r in ("BE","TRAIL"): color = "#a855f7"
    return _badge(r, color)

def _rows_kv_html(t: Dict[str, Any]) -> str:
    def cv(k, default="—"):
        v = t.get(k, default)
        return default if v in (None, "", []) else _md_html(str(v))
    rows = []
    for k in ("ticket_id","symbol","side","qty","leverage","position_side","budget","score",
              "tp1","tp2","tp3","sl","eta_tp1_min","eta_tp2_min","eta_tp3_min",
              "prob_overall_pct","prob_tp1_pct","prob_tp2_pct","prob_tp3_pct",
              "tp_splits","expiry_ts","note"):
        rows.append(f"<tr><th style='text-align:left;padding:.35rem .6rem;background:#fafafa'>{k}</th>"
                    f"<td style='padding:.35rem .6rem'>{cv(k)}</td></tr>")
    return "\n".join(rows)

# --- UI routes (HTML) ---
@router.get("/ops/ui/ticket")
async def ui_ticket(ticket_id: str = Query(...), request: Request = None):
    _require_bearer(request)
    rec, _ = await _load_ticket(ticket_id)
    if not rec:
        with suppress(Exception):
            for it in ConfirmStore.pending():
                if str(it.get("ticket_id")) == str(ticket_id):
                    rec = it.get("req") or it
                    break
    if not rec:
        return _html("⚠️ לא נמצא כרטיס או שפג תוקפו.")

    base = PUBLIC_HOST.rstrip("/") if PUBLIC_HOST else (str(request.base_url).rstrip("/") if request else "")
    approve_url = f"{base}/ops/approve?ticket_id={ticket_id}"
    reject_url  = f"{base}/ops/reject?ticket_id={ticket_id}"

    body = (
        "<!doctype html><meta charset='utf-8'>"
        "<body style='font-family:sans-serif;max-width:880px;margin:2rem auto;line-height:1.45'>"
        f"<h2 style='margin:0 0 1rem 0'>Ticket Preview · <code>{_md_html(ticket_id)}</code></h2>"
        "<div style='margin:.5rem 0 1rem 0'>"
        f"<a href='{approve_url}' style='display:inline-block;padding:.6rem 1rem;background:#16a34a;color:#fff;border-radius:9px;text-decoration:none'>✅ Approve</a>"
        f"<a href='{reject_url}' style='display:inline-block;padding:.6rem 1rem;background:#dc2626;color:#fff;border-radius:9px;text-decoration:none;margin-left:.6rem'>❌ Reject</a>"
        "</div>"
        "<table style='border-collapse:collapse;width:100%;border:1px solid #eee'>"
        f"{_rows_kv_html(rec)}"
        "</table>"
        "<p style='color:#777;margin-top:1rem'>טיפ: ניתן לקרוא/לאשר גם מהטלגרם.</p>"
        "</body>"
    )
    return HTMLResponse(body)

@router.get("/ops/ui/pending")
async def ui_pending(request: Request = None):
    _require_bearer(request)
    base = PUBLIC_HOST.rstrip("/") if PUBLIC_HOST else (str(request.base_url).rstrip("/") if request else "")
    items: List[Dict[str, Any]] = []

    if aioredis and REDIS_URL:
        with suppress(Exception):
            r = await _redis()
            if r:
                cursor: Any = 0
                while True:
                    res = await r.scan(cursor, match=f"{NS}:ticket:*", count=200)
                    cursor = int(res[0]) if not isinstance(res[0], int) else res[0]
                    keys = res[1]
                    for k in keys:
                        raw = await r.get(k)
                        if not raw:
                            continue
                        obj = json.loads(raw)
                        req = obj.get("req") or {}
                        items.append(req)
                    if cursor == 0:
                        break

    with suppress(Exception):
        for it in ConfirmStore.pending() or []:
            req = it.get("req") or it
            items.append(req)

    if not items:
        return _html("אין כרטיסים ממתינים כרגע.")

    rows = []
    for t in items:
        raw_tid = str(t.get("ticket_id",""))
        tid_disp = _md_html(raw_tid)
        sym = _md_html(str(t.get("symbol","")))
        side = _md_html(str(t.get("side","")))
        qty = _md_html(str(t.get("qty","")))
        lev = _md_html(str(t.get("leverage","")))
        link = f"{base}/ops/ui/ticket?ticket_id={raw_tid}"
        rows.append(
            f"<tr>"
            f"<td style='padding:.4rem .6rem'><a href='{link}'>👁 {tid_disp}</a></td>"
            f"<td style='padding:.4rem .6rem'>{sym}</td>"
            f"<td style='padding:.4rem .6rem'>{side}</td>"
            f"<td style='padding:.4rem .6rem'>{qty}</td>"
            f"<td style='padding:.4rem .6rem'>{lev}</td>"
            f"</tr>"
        )

    body = (
        "<!doctype html><meta charset='utf-8'>"
        "<body style='font-family:sans-serif;max-width:880px;margin:2rem auto;line-height:1.5'>"
        "<h2 style='margin:0 0 1rem 0'>Pending Approval Tickets</h2>"
        "<table style='border-collapse:collapse;width:100%;border:1px solid #eee'>"
        "<thead><tr style='background:#fafafa'><th style='text-align:left;padding:.4rem .6rem'>Ticket</th>"
        "<th style='text-align:left;padding:.4rem .6rem'>Symbol</th>"
        "<th style='text-align:left;padding:.4rem .6rem'>Side</th>"
        "<th style='text-align:left;padding:.4rem .6rem'>Qty</th>"
        "<th style='text-align:left;padding:.4rem .6rem'>Lev</th>"
        "</tr></thead>"
        "<tbody>"
        + "\n".join(rows) +
        "</tbody></table>"
        "</body>"
    )
    return HTMLResponse(body)

# --- Approve/Reject flows ---
@router.get("/ops/approve")
async def approve(ticket_id: str = Query(..., description="ticket_id")):
    ticket, source = await _load_ticket(ticket_id)
    if not ticket:
        return _html("⚠️ קישור שגוי או שפג תוקף האישור.")
    flow = _decide_flow_by_mode(ticket)

    with suppress(Exception):
        for k in ("blocked_by_rr_min","blocked_by_velocity","velocity_error"):
            ticket.pop(k, None)

    t2 = _apply_auto_qty_on_ticket(ticket)
    if t2 is None:
        return _html("⚠️ שגיאה: לא ניתן להביא מחיר עדכני לצורך חישוב כמות אוטומטית.")
    ticket = t2
    if float(ticket.get("qty") or 0) <= 0 or int(ticket.get("leverage") or 0) <= 0:
        return _html("⚠️ שגיאה: qty/leverage חסרים גם לאחר ניסיון חישוב אוטומטי (בדוק ENV AUTO_QTY_*).")

    exec_res = await (_execute_trade(ticket) if flow=="MARKET"
                      else _execute_trade_armed(ticket) if flow=="HYBRID"
                      else (_execute_trade_armed(ticket) if any(ticket.get(k) for k in ("tp1","tp2","tp3","sl")) else _execute_trade(ticket)))
    ok = bool(exec_res.get("ok"))

    if (not ok) and flow in ("HYBRID","AUTO") and APPROVE_FALLBACK_TO_MARKET:
        logger.warning("approve_retry_market_after_hybrid_fail: %s", exec_res)
        retry_res = await _execute_trade(ticket)
        ok = bool(retry_res.get("ok"))
        exec_res = {"primary": "HYBRID", "fallback_market": retry_res, "primary_error": exec_res}

    if ok:
        try:
            sm = _smart_manage_env()
            if sm["enable"]:
                sym = str(ticket.get("symbol","")).upper()
                sm_result = await _smart_manage_now(sym,
                                                    offset_bps=sm["offset_bps"],
                                                    pcts=sm["pcts"],
                                                    splits=sm["splits"],
                                                    atr_mult=sm["atr_mult"])
                logger.info("smart_manage_after_approve: %s -> %s", sym, sm_result)
        except Exception as e:
            logger.warning("smart_manage_after_approve_failed: %s", e)

        with suppress(Exception):
            sym = str(ticket.get("symbol","")).upper()
            ensure_protective_stop(sym, prefer_mode="quantities")

    if not ok:
        logger.warning("approve_failed: ticket=%s flow=%s detail=%s", ticket_id, flow, json.dumps(exec_res, ensure_ascii=False))

    try:
        sym, side, qty = ticket.get("symbol",""), ticket.get("side",""), ticket.get("qty","")
        msg = (
            f"✅ <b>Approved</b>\n• Ticket: <code>{_md_html(ticket_id)}</code>\n"
            f"• {_md_html(sym)} {_md_html(side)} qty={qty}\n• Flow: <code>{flow}</code>\n— — —\nבוצע והועבר לניהול."
            if ok else
            f"⚠️ <b>Approve Failed</b>\n• Ticket: <code>{_md_html(ticket_id)}</code>\n"
            f"• {_md_html(sym)} {_md_html(side)} qty={qty}\n• Flow: <code>{flow}</code>\n— — —\n"
            f"שגיאה: <code>{_md_html(json.dumps(exec_res, ensure_ascii=False))}</code>"
        )
        await _send_telegram_html(msg)
    except Exception:
        pass

    with suppress(Exception):
        ConfirmStore.decide(ticket_id, approved=ok)

    with suppress(Exception):
        (record_approval_approved if ok else record_approval_rejected)()

    await _delete_ticket(ticket_id, source)

    if ok:
        return _html("✅ אושר — הוזמן ונכנס לניהול דינמי.")
    if DEBUG_APPROVE_HTML:
        return _html("⚠️ שגיאה בביצוע — " + _md_html(json.dumps(exec_res, ensure_ascii=False)))
    return _html("⚠️ שגיאה בביצוע — ראה פירוט בטלגרם/לוגים.")

@router.get("/ops/approve-link")
async def approve_link(id: str = Query(..., description="ticket_id")):
    return await approve(ticket_id=id)

@router.get("/ops/reject")
async def reject(ticket_id: str = Query(..., description="ticket_id")):
    ticket, source = await _load_ticket(ticket_id)
    await _delete_ticket(ticket_id, source)
    with suppress(Exception):
        await _send_telegram_html(
            f"❌ <b>Rejected</b>\n• Ticket: <code>{_md_html(ticket_id)}</code>\n— — —\nNo action was taken."
        )
    with suppress(Exception):
        ConfirmStore.decide(ticket_id, approved=False)
    with suppress(Exception):
        record_approval_rejected()
    return _html("❌ נדחה. לא בוצעה פעולה.")

@router.post("/ops/approve/signed")
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

    t2 = _apply_auto_qty_on_ticket(payload)
    if t2 is None:
        raise HTTPException(status_code=400, detail="AUTO_QTY: failed to fetch last price")
    payload = t2
    if float(payload.get("qty") or 0) <= 0 or int(payload.get("leverage") or 0) <= 0:
        raise HTTPException(status_code=400, detail="AUTO_QTY: qty/leverage missing after auto sizing")

    flow = _decide_flow_by_mode(payload)
    exec_res = await (_execute_trade(payload) if flow=="MARKET"
                      else _execute_trade_armed(payload) if flow=="HYBRID"
                      else (_execute_trade_armed(payload) if any(payload.get(k) for k in ("tp1","tp2","tp3","sl")) else _execute_trade(payload)))
    ok = bool(exec_res.get("ok"))
    if not ok:
        logger.warning("approve_signed_failed: %s", json.dumps(exec_res, ensure_ascii=False))
        if flow in ("HYBRID","AUTO") and APPROVE_FALLBACK_TO_MARKET:
            retry = await _execute_trade(payload)
            if not retry.get("ok"):
                raise HTTPException(status_code=502, detail={"execute_error": exec_res, "fallback_market": retry})
            exec_res = {"primary": exec_res, "fallback_market": retry}
        else:
            raise HTTPException(status_code=502, detail={"execute_error": exec_res})

    try:
        sm = _smart_manage_env()
        if sm["enable"]:
            sym = str(payload.get("symbol","")).upper()
            sm_result = await _smart_manage_now(sym,
                                                offset_bps=sm["offset_bps"],
                                                pcts=sm["pcts"],
                                                splits=sm["splits"],
                                                atr_mult=sm["atr_mult"])
            logger.info("smart_manage_after_approve_signed: %s -> %s", sym, sm_result)
    except Exception as e:
        logger.warning("smart_manage_after_approve_signed_failed: %s", e)

    with suppress(Exception):
        sym = str(payload.get("symbol","")).upper()
        ensure_protective_stop(sym, prefer_mode="quantities")

    with suppress(Exception):
        record_approval_approved()
    return {"ok": True, "ticket_id": payload.get("ticket_id"), "executed": True, "flow": flow, "internal_execute": exec_res}

# --- Guard smoke run ---
@router.post("/guard/smoke/run")
async def guard_smoke_run(request: Request, symbols: Optional[str] = Body(None)):
    _require_bearer(request)

    if "ensure_protective_stop" not in globals():
        raise HTTPException(status_code=501, detail="ensure_protective_stop() not available")

    if isinstance(symbols, str) and symbols.strip():
        sym_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    else:
        sym_list = [s.strip().upper() for s in (os.getenv("WATCHLIST","") or "").split(",") if s.strip()]
    if not sym_list:
        raise HTTPException(status_code=400, detail="no symbols to check")

    results: Dict[str, Any] = {}
    emergencies: List[str] = []

    for s in sym_list:
        try:
            res = ensure_protective_stop(s, prefer_mode="quantities")
        except Exception as e:
            res = {"ok": False, "error": str(e)}

        results[s] = res

        flag = False
        try:
            if isinstance(res, dict):
                flag = bool(res.get("emergency")) or bool(res.get("placed")) or (str(res.get("action","")).lower() in ("emergency","place"))
        except Exception:
            pass
        if flag:
            emergencies.append(s)

    if emergencies:
        lines = ["🚨 <b>Smoke Guard</b> · Emergency protective SL placed", f"• Symbols: <code>{','.join(emergencies)}</code>"]
        await _send_telegram_html("\n".join(lines))

    return {"ok": True, "checked": sym_list, "emergencies": emergencies, "results": results}

# --- Ops digest: expired approvals ---
@router.get("/ops/digest/expired")
async def digest_expired(hours: int = Query(6, ge=1, le=48)):
    if not (aioredis and REDIS_URL and BOT_TOKEN and ADMIN_CHAT_ID):
        return {"ok": False, "error": "digest_dependencies_missing"}
    try:
        r = await _redis()
        if not r:
            return {"ok": False, "error": "redis_unavailable"}

        key_good = f"{NS}:expired_log"
        key_bad  = key_good + "}"

        items: List[str] = []
        with suppress(Exception):
            items.extend(await r.lrange(key_good, 0, 2000) or [])
        with suppress(Exception):
            items.extend(await r.lrange(key_bad, 0, 2000) or [])

        now = time.time()
        since = now - (hours * 3600)

        events: List[Dict[str, Any]] = []
        for it in items:
            try:
                obj = json.loads(it)
                if float(obj.get("ts", 0)) >= since:
                    events.append(obj)
            except Exception:
                continue
        events.sort(key=lambda x: x.get("ts", 0), reverse=True)
        total = len(events)
        if total == 0:
            await _send_telegram_html(f"ℹ️ No expired approvals in last {hours}h.")
            return {"ok": True, "sent": True, "count": 0}

        by_sym = Counter((str(e.get("symbol","")).upper(), str(e.get("side","")).upper()) for e in events)
        lines = [f"⏱️ <b>Expired approvals</b> (last {hours}h) · total: <b>{total}</b>"]
        for (sym, side), cnt in by_sym.most_common(20):
            lines.append(f"• {sym} {side}: <code>{cnt}</code>")
        lines.append("— — —")
        lines.append("<b>Last events</b>:")
        for e in events[:5]:
            t = int(e.get("ts", now))
            idem = e.get("idem","")
            sym  = str(e.get("symbol","")).upper()
            side = str(e.get("side","")).upper()
            lines.append(f"• {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(t))}Z · {sym} {side} · <code>{idem}</code>")
        await _send_telegram_html("\n".join(lines))
        return {"ok": True, "sent": True, "count": total}
    except Exception as e:
        logger.warning("digest_expired_failed: %s", e)
        return {"ok": False, "error": str(e)}

# --- Register routers ---
app.include_router(router)

# Extra routers (best-effort)
with suppress(Exception):
    from routes.position_ops import router as position_ops_router  # type: ignore
    app.include_router(position_ops_router)

with suppress(Exception):
    from routes.locked_report import router as locked_router  # type: ignore
    app.include_router(locked_router)

with suppress(Exception):
    from routes.scan_public import router as scan_public_router  # type: ignore
    app.include_router(scan_public_router)

with suppress(Exception):
    from routes.scan_top_volume import router as scan_router  # type: ignore
    app.include_router(scan_router)

with suppress(Exception):
    from routes.topk import router as topk_router  # type: ignore
    app.include_router(topk_router)

# >>> aggregate root router (if exists) <<<
with suppress(Exception):
    from routes import root as routes_root
    app.include_router(routes_root.router)

# --- Meta routes ---
@app.get("/", response_class=PlainTextResponse, tags=["meta"])
def root() -> str:
    name = os.getenv("APP_NAME", "algogpt")
    return f"{name} online"

@app.head("/", response_class=PlainTextResponse, tags=["meta"])
def root_head() -> str:
    return ""

@app.get("/health", response_class=PlainTextResponse, tags=["meta"])
@app.head("/health", response_class=PlainTextResponse)
def health() -> str:
    return "ok"

@app.get("/healthz", response_class=PlainTextResponse, tags=["meta"])
def healthz() -> str:
    return "ok"

@app.get("/readyz", response_class=PlainTextResponse, tags=["meta"])
def readyz() -> str:
    return "ok"

# ---- Added to satisfy curl checks ----
@app.get("/health/live", response_class=PlainTextResponse, tags=["meta"])
def health_live() -> str:
    return "ok"

@app.get("/health/strategy-version", tags=["meta"])
def health_strategy_version() -> Dict[str, str]:
    return {"ok": True, "version": os.getenv("ALGOGPT_VERSION", "unknown")}

@app.get("/debug/env", tags=["debug"])
def debug_env(keys: Optional[str] = None) -> Dict[str, Any]:
    allowlist = set([k.strip() for k in (keys or "").split(",") if k.strip()]) if keys else set()
    safe: Dict[str, Any] = {}
    for k, v in os.environ.items():
        if any(x in k.upper() for x in ("SECRET", "TOKEN", "KEY", "PASSWORD")):
            continue
        if allowlist and k not in allowlist:
            continue
        safe[k] = v
    return {"ok": True, "env": safe}

# --- Health TP1 utils (use real module; no fallback if present) ---
try:
    from utils.health_tp1 import health_check_tp1_tags, quick_check_tp1  # type: ignore
    _health_tp1_loaded = True
except Exception as _e:
    logger.warning("health_tp1 utils import failed: %s", _e)
    _health_tp1_loaded = False

@app.get("/health/tp1", tags=["meta"])
async def health_tp1_now(symbols: Optional[str] = Query(None, description="CSV of symbols; default from WATCHLIST")):
    if not _health_tp1_loaded:
        raise HTTPException(status_code=501, detail="health_tp1 module not loaded")
    sym_list = [s.strip().upper() for s in (symbols.split(",") if symbols else (os.getenv("WATCHLIST","") or "").split(",")) if s.strip()]
    if not sym_list:
        raise HTTPException(status_code=400, detail="no symbols")
    res = await quick_check_tp1(sym_list, tp1_tags=(os.getenv("TP1_TAGS","") or None), notify_telegram=True)
    return {"ok": True, "result": res}

# --- Global error handler ---
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("unhandled_error: %s %s", request.method, request.url)
    return JSONResponse(
        status_code=500,
        content={"ok": False, "error": "internal_error", "detail": str(exc)},
    )
# =================================================
# Startup background tasks
# =================================================
_manager_lock = asyncio.Lock()
_manager_backoff = 0.0  # seconds

@app.on_event("startup")
async def _startup_tasks():
    if getattr(app.state, "bg_started", False):
        logger.info("startup: background already started – skipping")
        return
    app.state.bg_started = True

    async def _notify_bot_online():
        with suppress(Exception):
            await asyncio.sleep(0.7)
            name = os.getenv("APP_TITLE", "AlgoGPT Supervisor")
            env  = os.getenv("ENV", os.getenv("ENVIRONMENT","prod"))
            await _send_telegram_html(f"🟢 <b>Bot online</b> · <code>{name}</code> · env=<code>{env}</code>")
    asyncio.create_task(_notify_bot_online())

    # Health TP1 watchdog
    if _health_tp1_loaded and (os.getenv("HEALTH_TP1_ENABLE","1").lower() in ("1","true","yes","on")):
        watch = [s.strip() for s in (os.getenv("WATCHLIST","") or "").split(",") if s.strip()]
        if watch:
            asyncio.create_task(health_check_tp1_tags(watch, interval_sec=int(os.getenv("HEALTH_TP1_INTERVAL_SEC","600"))))
            logger.info("health_tp1 background started (interval=%ss, symbols=%s)",
                        int(os.getenv("HEALTH_TP1_INTERVAL_SEC","600")), ",".join(watch))

    # Periodic manager calls
    async def periodic_manager():
        global _manager_backoff
        await asyncio.sleep(2.0)
        token = API_BEARER_TOKEN
        if not token:
            logger.info("periodic_manager: missing API_BEARER_TOKEN; skipping")
            return
        syms = [s.strip() for s in (os.getenv("WATCHLIST","") or "").split(",") if s.strip()]
        if not syms:
            return
        base = get_internal_base()
        every_sec = max(10, int(os.getenv("TRADE_MANAGER_INTERVAL_SEC","60")))
        per_req_timeout = httpx.Timeout(connect=2.5, read=15.0, write=10.0, pool=10.0)
        while True:
            sleep_extra = _manager_backoff
            if sleep_extra > 0:
                await asyncio.sleep(sleep_extra)
            async with _manager_lock:
                try:
                    async with httpx.AsyncClient(timeout=per_req_timeout) as cli:
                        for s in syms:
                            r = await cli.post(
                                f"{base}/position-ops/manage-once",
                                headers={"Authorization": f"Bearer {token}"},
                                json={"symbol": s}
                            )
                            if r.status_code < 400:
                                _manager_backoff = max(0.0, _manager_backoff * 0.5 - 2.0)
                            elif r.status_code in (429, 500, 502, 503, 504):
                                _manager_backoff = min((_manager_backoff or 0) * 1.6 + 5, 90)
                                logger.warning("periodic_manager_backoff: status=%s backoff=%ss", r.status_code, _manager_backoff)
                            else:
                                logger.warning("periodic_manager_unexpected_status: %s %s", r.status_code, r.text[:200])
                except Exception as e:
                    _manager_backoff = min((_manager_backoff or 0) * 1.5 + 5, 90)
                    logger.warning("periodic_manager_error: %r (backoff now %.1fs)", e, _manager_backoff)
            await asyncio.sleep(every_sec)

    if os.getenv("MANAGER_ENABLE","1").lower() in ("1","true","yes","on"):
        asyncio.create_task(periodic_manager())

    # Guarder
    async def periodic_guarder():
        await asyncio.sleep(3.0)
        syms = [s.strip().upper() for s in (os.getenv("WATCHLIST","") or "").split(",") if s.strip()]
        if not syms:
            return
        while True:
            try:
                for s in syms:
                    with suppress(Exception):
                        ensure_protective_stop(s, prefer_mode="quantities")
            except Exception:
                pass
            await asyncio.sleep(int(os.getenv("GUARDER_INTERVAL_SEC","45")))
    if os.getenv("GUARDER_ENABLE","1").lower() in ("1","true","yes","on"):
        asyncio.create_task(periodic_guarder())

    # Scanner
    async def periodic_scanner():
        try:
            from routes.scan_top_volume import scan_top_volume  # type: ignore
        except Exception as e:
            logger.warning("periodic_scanner_unavailable: %s", e)
            return

        await asyncio.sleep(4.0)
        every       = int(os.getenv("SCAN_CRON_EVERY_SEC", "45") or "45")
        tf          = os.getenv("SCAN_CRON_TIMEFRAME", "15m") or "15m"
        kline_limit = int(os.getenv("SCAN_CRON_KLINES", "200") or "200")
        limit       = int(os.getenv("SCAN_CRON_LIMIT", "12") or "12")
        min_score   = float(os.getenv("SCAN_CRON_MIN_SCORE", "7.0") or "7.0")
        rearm_score = float(os.getenv("SCAN_REARM_SCORE", "6.0") or "6.0")
        dedupe_sec  = int(os.getenv("SCAN_DEDUPE_WINDOW_SEC", "300") or "300")
        ttl_sec     = int(os.getenv("SCAN_TTL_SEC", "900") or "900")
        leverage    = float(os.getenv("DEFAULT_LEVERAGE", "5") or "5")
        stake       = float(os.getenv("DEFAULT_STAKE_USDT", "50") or "50")
        rich        = (os.getenv("SCAN_RICH", "1").lower() in ("1","true","yes","on"))
        chat        = os.getenv("TELEGRAM_CHAT_ID")

        if not chat:
            logger.info("periodic_scanner: TELEGRAM_CHAT_ID missing; skipping")
            return

        while True:
            try:
                await scan_top_volume(
                    market="futures",
                    quote="USDT",
                    limit=limit,
                    timeframe=tf,
                    kline_limit=kline_limit,
                    min_score=min_score,
                    require_side=True,
                    notify="telegram",
                    chat_id=str(chat),
                    rich=rich,
                    ttl_sec=ttl_sec,
                    rearm_score=rearm_score,
                    dedupe_window_sec=dedupe_sec,
                    leverage=leverage,
                    stake_usdt=stake,
                )
            except Exception as e:
                logger.warning("periodic_scanner_error: %s", e)
            await asyncio.sleep(max(10, every))

    if os.getenv("SCAN_CRON_ENABLE","1").lower() in ("1","true","yes","on"):
        asyncio.create_task(periodic_scanner())

# =================================================
# Uvicorn entry
# =================================================
if __name__ == "__main__":
    import uvicorn
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "10000"))
    reload_ = os.getenv("UVICORN_RELOAD", "0").lower() in ("1", "true", "yes", "on")
    uvicorn.run("main:app", host=host, port=port, reload=reload_)

























































































































































































































































































































































































































































































































































































































































