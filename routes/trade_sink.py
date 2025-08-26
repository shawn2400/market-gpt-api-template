# routes/trade_sink.py
from __future__ import annotations
from fastapi import APIRouter, Depends, Body, Header, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
import os, time, json, httpx

try:
    from utils.auth import require_api_key
except Exception:
    def require_api_key():
        return None

# ✅ משתמשים ב-hmac_utils האחוד
from utils.hmac_utils import verify_hmac, idem_seen
from utils.redis_client import redis_client as RED

router = APIRouter(prefix="/alerts", tags=["Alerts"], dependencies=[Depends(require_api_key)])

BOT = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID_DEFAULT = os.getenv("TELEGRAM_CHAT_ID", "").strip()
TELEGRAM_API = f"https://api.telegram.org/bot{BOT}"
TIMEOUT = float(os.getenv("TELEGRAM_HTTP_TIMEOUT", "15"))

USE_REDIS_TRADES = os.getenv("USE_REDIS_TRADES","0").lower() in ("1","true","yes")

if USE_REDIS_TRADES and not RED:
    # יש קונפיג ל-Redis אבל אין חיבור זמין → נמשיך in-memory כדי לא להפיל השרת
    USE_REDIS_TRADES = False

# ====== Models ======
class TradeIn(BaseModel):
    trade_id: str = Field(..., min_length=4, max_length=64)
    trade_type: str = Field(..., pattern="^(FUTURES|SPOT|GRID)$")
    symbol: str
    side: Optional[str] = None           # FUTURES/SPOT (LONG/SHORT; ב-SPOT רק LONG)
    current_price: float

    # FUTURES/SPOT
    entry: Optional[float] = None
    sl: Optional[float] = None
    tp1: Optional[float] = None
    tp2: Optional[float] = None
    tp3: Optional[float] = None
    success_pct: Optional[float] = None
    reason: Optional[str] = None
    leverage: Optional[int] = None
    budget_usd: Optional[float] = None
    notional_usd: Optional[float] = None
    qty: Optional[float] = None

    # ETA (אופציונלי, לפי worker/bot)
    eta_sl: Optional[str] = None
    eta_tp1: Optional[str] = None
    eta_tp2: Optional[str] = None
    eta_tp3: Optional[str] = None

    # GRID
    grid_min: Optional[float] = None
    grid_max: Optional[float] = None
    grid_levels: Optional[int] = None
    grid_step_pct: Optional[float] = None
    grid_take_profit_pct: Optional[float] = None
    grid_side: Optional[str] = None

    # misc
    tp_scale: Optional[str] = None       # JSON [50,30,20]
    chat_id: int | str | None = None

class TradeOut(BaseModel):
    ok: bool = True
    trade_id: str
    message_id: Optional[int] = None
    chat_id: Optional[str | int] = None

# ====== Store (Redis/In-Mem) ======
_TRADES: Dict[str, Dict[str, Any]] = {}

def _store_trade(item: Dict[str, Any]):
    if USE_REDIS_TRADES and RED:
        key = f"trades:active:{item['trade_id']}"
        # Redis expects str mapping
        mapping = {k: (json.dumps(v) if isinstance(v, (dict, list)) else str(v)) for k, v in item.items()}
        RED.hset(key, mapping=mapping)
        RED.sadd("trades:active:set", item["trade_id"])
    else:
        _TRADES[item["trade_id"]] = item

def _get_trade(tid: str) -> Optional[Dict[str, Any]]:
    if USE_REDIS_TRADES and RED:
        d = RED.hgetall(f"trades:active:{tid}")
        return d or None
    return _TRADES.get(tid)

def _all_active() -> List[Dict[str, Any]]:
    if USE_REDIS_TRADES and RED:
        tids = RED.smembers("trades:active:set") or []
        out: List[Dict[str, Any]] = []
        for tid in tids:
            d = RED.hgetall(f"trades:active:{tid}")
            if d: out.append(d)
        return out
    return list(_TRADES.values())

def _update_trade(tid: str, **updates):
    if USE_REDIS_TRADES and RED:
        key = f"trades:active:{tid}"
        if not RED.exists(key): return
        mapping = {k: (json.dumps(v) if isinstance(v, (dict, list)) else str(v)) for k, v in updates.items()}
        RED.hset(key, mapping=mapping)
    else:
        if tid in _TRADES:
            _TRADES[tid].update(updates)

# ====== Formatting ======
def _fmt(x) -> str:
    try:
        return f"{float(x):.6f}"
    except Exception:
        return "—"

def _format_trade_message(rec: Dict[str, Any]) -> str:
    ttype = str(rec.get("trade_type","FUTURES")).upper()
    sym   = rec.get("symbol","")
    nowp  = _fmt(rec.get("current_price"))
    header = f"🟢 *{ttype}* Suggestion • #{rec['trade_id']}\n*{sym}*"

    # GRID
    if ttype == "GRID":
        side = rec.get("grid_side") or "LONG"
        grid_min = _fmt(rec.get("grid_min"))
        grid_max = _fmt(rec.get("grid_max"))
        levels   = rec.get("grid_levels") or "—"
        step_pct = rec.get("grid_step_pct") or 0.0
        tp_pct   = rec.get("grid_take_profit_pct")
        lines = [
            header + f"  [{side}]",
            f"Now: `{nowp}`  Range: `{grid_min}` – `{grid_max}`",
            f"Levels: *{levels}*  Step≈*{(float(step_pct) if step_pct else 0):.2f}%*  TP/fill: *{(tp_pct or 0):.2f}%*",
        ]
        if rec.get("budget_usd"):
            lines.append(f"Budget: ${float(rec['budget_usd']):.2f}")
        if rec.get("reason"):
            lines.append(f"_Reason_: {rec.get('reason')}")
        return "\n".join(lines)

    # FUTURES / SPOT
    side = rec.get("side","")
    lev  = f"x{rec.get('leverage')}" if (ttype=="FUTURES" and rec.get("leverage")) else ""
    lines = [
        header + f" {side} {lev}",
        f"Now: `{nowp}`  Entry: `{_fmt(rec.get('entry'))}`",
        f"SL: `{_fmt(rec.get('sl'))}`  TP1: `{_fmt(rec.get('tp1'))}`  TP2: `{_fmt(rec.get('tp2'))}`  TP3: `{_fmt(rec.get('tp3'))}`",
    ]
    if rec.get("success_pct") is not None:
        lines.append(f"Success: *{float(rec['success_pct']):.1f}%*")
    if rec.get("notional_usd") is not None:
        lines.append(
            f"Budget: ${rec.get('budget_usd') or '—'}  Notional: ${float(rec['notional_usd']):.2f}  Qty: {_fmt(rec.get('qty'))}"
        )
    if rec.get("tp_scale"):
        try:
            p = json.loads(rec["tp_scale"]) if isinstance(rec["tp_scale"], str) else rec["tp_scale"]
            if isinstance(p, list) and len(p) == 3:
                lines.append(f"TP Scale: {int(p[0])}/{int(p[1])}/{int(p[2])}%")
        except Exception:
            pass
    if rec.get("reason"):
        lines.append(f"_Reason_: {rec['reason']}")
    return "\n".join(lines)

def _inline_keyboard(trade_id: str) -> dict:
    """
    כפתורים מינימליסטיים ויעילים:
    - SL→BE
    - TP Scale (מבקש מהבוט להציג פורמט /tp_scale)
    """
    return {
        "inline_keyboard":[
            [{"text":"🔒 SL→BE", "callback_data":f"slbe:{trade_id}"}],
            [{"text":"📊 TP Scale", "callback_data":f"tpask:{trade_id}"}]
        ]
    }

# ====== Endpoints ======
@router.post("/trade-ingest", response_model=TradeOut)
async def trade_ingest(
    payload: TradeIn = Body(...),
    x_idempotency_key: Optional[str] = Header(default=None, convert_underscores=False),
    x_signature: Optional[str] = Header(default=None, convert_underscores=False),
):
    if not BOT:
        raise HTTPException(500, "TELEGRAM_BOT_TOKEN not configured")

    raw = json.dumps(payload.model_dump(), separators=(",", ":"), ensure_ascii=False).encode()
    if not verify_hmac(x_signature, raw):
        raise HTTPException(401, "Invalid signature")

    if x_idempotency_key and idem_seen(x_idempotency_key):
        rec = _get_trade(payload.trade_id) or {}
        return TradeOut(ok=True, trade_id=payload.trade_id, message_id=int(rec.get("message_id") or 0) or None, chat_id=rec.get("chat_id"))

    rec = payload.model_dump()
    rec.update({
        "status":"active",
        "ts": int(time.time()),
        "hits": json.dumps({"tp1":False,"tp2":False,"tp3":False,"sl":False}),
        "near": json.dumps({"tp1":False,"tp2":False,"tp3":False,"sl":False}),
    })

    # GRID: חישוב קווי רשת לשימוש עתידי ב-watchdog
    if rec["trade_type"] == "GRID":
        try:
            gmin = float(rec.get("grid_min") or 0)
            gmax = float(rec.get("grid_max") or 0)
            L    = int(rec.get("grid_levels") or 0)
            if gmin > 0 and gmax > 0 and L >= 2:
                step = (gmax - gmin) / (L - 1)
                lines = [gmin + i * step for i in range(L)]
                rec["grid_lines"] = json.dumps(lines)
        except Exception:
            rec["grid_lines"] = json.dumps([])

    txt = _format_trade_message(rec)
    kb = _inline_keyboard(rec["trade_id"])

    body = {
        "chat_id": payload.chat_id or CHAT_ID_DEFAULT,
        "text": txt,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
        "reply_markup": kb,
    }
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.post(f"{TELEGRAM_API}/sendMessage", json=body)
        r.raise_for_status()
        resp = r.json()
        msg = resp.get("result", {})
        rec["chat_id"] = body["chat_id"]
        rec["message_id"] = msg.get("message_id")
        _store_trade(rec)
        return TradeOut(ok=True, trade_id=rec["trade_id"], message_id=rec["message_id"], chat_id=rec["chat_id"])

# Active list
class ActiveOut(BaseModel):
    ok: bool = True
    count: int
    items: List[Dict[str, Any]]

@router.get("/trades/active", response_model=ActiveOut)
def trades_active():
    items = _all_active()
    return ActiveOut(ok=True, count=len(items), items=items)

# Update
class UpdateReq(BaseModel):
    trade_id: str
    updates: Dict[str, Any]

@router.post("/trades/update", response_model=dict)
def trades_update(payload: UpdateReq):
    _update_trade(payload.trade_id, **payload.updates)
    return {"ok": True}

# Analysis (notify)
class AnalysisIn(BaseModel):
    chat_id: int | str
    text: str
    reply_to_message_id: Optional[int] = None
    silent: Optional[bool] = True
    reply_markup: Optional[dict] = None  # ✅ מאפשר כפתורים

@router.post("/analysis", response_model=dict)
async def analysis_ingest(
    payload: AnalysisIn = Body(...),
    x_idempotency_key: Optional[str] = Header(default=None, convert_underscores=False),
    x_signature: Optional[str] = Header(default=None, convert_underscores=False),
):
    raw = json.dumps(payload.model_dump(), separators=(",", ":"), ensure_ascii=False).encode()
    if not verify_hmac(x_signature, raw):
        raise HTTPException(401, "Invalid signature")
    if x_idempotency_key and idem_seen(x_idempotency_key):
        return {"ok": True, "status": "duplicate_ignored"}

    if not BOT:
        raise HTTPException(500, "TELEGRAM_BOT_TOKEN not configured")

    body = {
        "chat_id": payload.chat_id,
        "text": payload.text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }
    if payload.reply_to_message_id:
        body["reply_to_message_id"] = payload.reply_to_message_id
    if payload.silent:
        body["disable_notification"] = True
    if payload.reply_markup:
        body["reply_markup"] = payload.reply_markup

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.post(f"{TELEGRAM_API}/sendMessage", json=body)
        r.raise_for_status()
        return {"ok": True}







