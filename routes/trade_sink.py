# routes/trade_sink.py
from __future__ import annotations
from fastapi import APIRouter, Depends, Body, Header, HTTPException, Request
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
import os, time, json, httpx

try:
    from utils.auth import require_api_key
except Exception:
    def require_api_key():
        return None

from utils.hmac_utils import (
    HDR_SIGNATURE, HDR_TIMESTAMP, HDR_IDEMPOTENCY,
    check_inbound,  # אימות HMAC+Timestamp
)
from utils.redis_client import redis_client as RED

router = APIRouter(prefix="/alerts", tags=["Alerts"], dependencies=[Depends(require_api_key)])

# ---------- ENV ----------
BOT = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID_DEFAULT = os.getenv("TELEGRAM_CHAT_ID", "").strip() or os.getenv("ADMIN_CHAT_ID","").strip()
TELEGRAM_API = f"https://api.telegram.org/bot{BOT}" if BOT else ""
TIMEOUT = float(os.getenv("TELEGRAM_HTTP_TIMEOUT", "15"))
WEBHOOK_HMAC_SECRET = os.getenv("WEBHOOK_HMAC_SECRET","").strip()  # סוד משותף לחתימה

USE_REDIS_TRADES = os.getenv("USE_REDIS_TRADES","0").lower() in ("1","true","yes")
IDEM_TTL_SEC = int(float(os.getenv("IDEM_TTL_SEC","86400")))  # 24h

# ---------- Storage ----------
if USE_REDIS_TRADES and RED:
    _TRADES: Dict[str, Dict[str, Any]] = {}  # לא בשימוש בפועל כשיש Redis
else:
    _TRADES: Dict[str, Dict[str, Any]] = {}

# Idempotency fallback (אם אין Redis)
_IDEM_LOCAL: Dict[str, float] = {}

def _idem_seen(key: Optional[str]) -> bool:
    """
    החזרת True אם מפתח כבר נראה (ונשמר) + שמירה כעת אם טרי.
    Redis עדיף; אם אין – זיכרון מקומי.
    """
    if not key:
        return False
    now = time.time()
    if RED:
        rkey = f"algogpt:idem:{key}"
        try:
            if RED.get(rkey):
                return True
            RED.set(rkey, "1", ex=IDEM_TTL_SEC)
            return False
        except Exception:
            # ניפול ל-local
            pass
    # local
    # ניקוי קל למפתחות ישנים
    stale = [k for k, ts in _IDEM_LOCAL.items() if (now - ts) > IDEM_TTL_SEC]
    for k in stale:
        _IDEM_LOCAL.pop(k, None)
    if key in _IDEM_LOCAL:
        return True
    _IDEM_LOCAL[key] = now
    return False

# ====== Models ======
class TradeIn(BaseModel):
    trade_id: str = Field(..., min_length=4, max_length=64)
    trade_type: str = Field(..., pattern="^(FUTURES|SPOT|GRID)$")
    symbol: str
    side: Optional[str] = None  # FUTURES / SPOT (LONG/SHORT; ב-SPOT רק LONG)
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
    chat_id: int | str | None = None

class TradeOut(BaseModel):
    ok: bool = True
    trade_id: str
    message_id: Optional[int] = None
    chat_id: Optional[str | int] = None

def _store_trade(item: Dict[str, Any]):
    if RED and USE_REDIS_TRADES:
        key = f"trades:active:{item['trade_id']}"
        mapping = {k: (json.dumps(v, ensure_ascii=False) if isinstance(v,(dict,list)) else str(v))
                   for k, v in item.items()}
        RED.hset(key, mapping=mapping)
        RED.sadd("trades:active:set", item["trade_id"])
    else:
        _TRADES[item["trade_id"]] = item

def _get_trade(tid: str) -> Optional[Dict[str, Any]]:
    if RED and USE_REDIS_TRADES:
        key = f"trades:active:{tid}"
        data = RED.hgetall(key)
        # הפוך JSON-ים לשדות מקוריים אם צריך
        if data:
            for k in ("hits","near","grid_lines"):
                if k in data and isinstance(data[k], str):
                    try:
                        data[k] = json.loads(data[k])
                    except Exception:
                        pass
        return data or None
    return _TRADES.get(tid)

def _all_active() -> List[Dict[str, Any]]:
    if RED and USE_REDIS_TRADES:
        tids = RED.smembers("trades:active:set") or []
        out = []
        for tid in tids:
            d = RED.hgetall(f"trades:active:{tid}")
            if d: out.append(d)
        return out
    return list(_TRADES.values())

def _update_trade(tid: str, **updates):
    if RED and USE_REDIS_TRADES:
        key = f"trades:active:{tid}"
        if not RED.exists(key):
            return
        mapping = {k: (json.dumps(v, ensure_ascii=False) if isinstance(v,(dict,list)) else str(v))
                   for k, v in updates.items()}
        RED.hset(key, mapping=mapping)
    else:
        if tid in _TRADES:
            _TRADES[tid].update(updates)

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
            f"Levels: *{levels}*  Step≈*{(float(step_pct) if step_pct else 0.0):.2f}%*  TP/fill: *{(float(tp_pct) if tp_pct else 0.0):.2f}%*",
        ]
        if rec.get("budget_usd"):
            lines.append(f"Budget: ${float(rec['budget_usd']):.2f}")
        if rec.get("reason"):
            lines.append(f"_Reason_: {rec['reason']}")
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
        lines.append(f"Budget: ${rec.get('budget_usd') or '—'}  Notional: ${float(rec['notional_usd']):.2f}  Qty: {_fmt(rec.get('qty'))}")
    if rec.get("reason"):
        lines.append(f"_Reason_: {rec['reason']}")
    return "\n".join(lines)

def _approve_keyboard(trade_id: str) -> dict:
    return {
        "inline_keyboard":[[
            {"text":"✅ אישור ידני", "callback_data":f"approve:{trade_id}"},
            {"text":"🧠 ניתוח GPT", "callback_data":f"analysis:{trade_id}"},
            {"text":"🛑 דחייה", "callback_data":f"reject:{trade_id}"},
        ]]
    }

# ========= Endpoints =========

@router.post("/trade-ingest", response_model=TradeOut)
async def trade_ingest(
    request: Request,
    payload: TradeIn = Body(...),
    x_signature: Optional[str] = Header(default=None, convert_underscores=False),
    x_timestamp: Optional[str] = Header(default=None, convert_underscores=False),
    x_idempotency_key: Optional[str] = Header(default=None, convert_underscores=False),
):
    if not BOT:
        raise HTTPException(500, "TELEGRAM_BOT_TOKEN not configured")
    if not WEBHOOK_HMAC_SECRET:
        raise HTTPException(500, "WEBHOOK_HMAC_SECRET not configured")

    # נבנה bytes קנוני מהמודל (תואם ל-sign_payload)
    raw = json.dumps(payload.model_dump(), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")

    # אימות HMAC+Timestamp
    headers = {
        HDR_SIGNATURE: x_signature or request.headers.get(HDR_SIGNATURE) or request.headers.get(HDR_SIGNATURE.lower()),
        HDR_TIMESTAMP: x_timestamp or request.headers.get(HDR_TIMESTAMP) or request.headers.get(HDR_TIMESTAMP.lower()),
    }
    ok, reason = check_inbound(WEBHOOK_HMAC_SECRET, headers, raw, tolerance_sec=300)
    if not ok:
        raise HTTPException(401, f"Invalid signature: {reason}")

    # Idempotency
    idem = x_idempotency_key or request.headers.get(HDR_IDEMPOTENCY) or request.headers.get(HDR_IDEMPOTENCY.lower())
    if _idem_seen(idem):
        rec = _get_trade(payload.trade_id) or {}
        mid = rec.get("message_id")
        return TradeOut(ok=True, trade_id=payload.trade_id, message_id=int(mid) if mid else None, chat_id=rec.get("chat_id"))

    # Persist
    rec = payload.model_dump()
    rec.update({
        "status":"active",
        "ts": int(time.time()),
        "hits": {"tp1":False,"tp2":False,"tp3":False,"sl":False},
        "near": {"tp1":False,"tp2":False,"tp3":False,"sl":False},
    })

    # GRID: הכנת קווי גריד ל-watchdog (אופציונלי)
    if rec["trade_type"] == "GRID":
        try:
            gmin = float(rec.get("grid_min") or 0)
            gmax = float(rec.get("grid_max") or 0)
            L    = int(rec.get("grid_levels") or 0)
            lines = []
            if gmin > 0 and gmax > 0 and L >= 2:
                step = (gmax - gmin) / (L - 1)
                lines = [gmin + i * step for i in range(L)]
            rec["grid_lines"] = lines
        except Exception:
            rec["grid_lines"] = []

    txt = _format_trade_message(rec)
    body = {
        "chat_id": payload.chat_id or CHAT_ID_DEFAULT,
        "text": txt,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
        "reply_markup": _approve_keyboard(payload.trade_id),
    }

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.post(f"{TELEGRAM_API}/sendMessage", json=body)
        r.raise_for_status()
        resp = r.json()
        msg = resp.get("result", {})
        rec["chat_id"] = body["chat_id"]
        rec["message_id"] = msg.get("message_id")
        _store_trade(rec)
        return TradeOut(ok=True, trade_id=payload.trade_id, message_id=rec["message_id"], chat_id=rec["chat_id"])

# ============ aux ============
class ActiveOut(BaseModel):
    ok: bool = True
    count: int
    items: List[Dict[str, Any]]

@router.get("/trades/active", response_model=ActiveOut)
def trades_active():
    items = _all_active()
    return ActiveOut(ok=True, count=len(items), items=items)

class UpdateReq(BaseModel):
    trade_id: str
    updates: Dict[str, Any]

@router.post("/trades/update", response_model=dict)
def trades_update(payload: UpdateReq):
    _update_trade(payload.trade_id, **payload.updates)
    return {"ok": True}

class AnalysisIn(BaseModel):
    chat_id: int | str
    text: str
    reply_to_message_id: Optional[int] = None
    silent: Optional[bool] = True

@router.post("/analysis", response_model=dict)
async def analysis_ingest(
    request: Request,
    payload: AnalysisIn = Body(...),
    x_signature: Optional[str] = Header(default=None, convert_underscores=False),
    x_timestamp: Optional[str] = Header(default=None, convert_underscores=False),
    x_idempotency_key: Optional[str] = Header(default=None, convert_underscores=False),
):
    if not BOT:
        raise HTTPException(500, "TELEGRAM_BOT_TOKEN not configured")
    if not WEBHOOK_HMAC_SECRET:
        raise HTTPException(500, "WEBHOOK_HMAC_SECRET not configured")

    raw = json.dumps(payload.model_dump(), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    headers = {
        HDR_SIGNATURE: x_signature or request.headers.get(HDR_SIGNATURE) or request.headers.get(HDR_SIGNATURE.lower()),
        HDR_TIMESTAMP: x_timestamp or request.headers.get(HDR_TIMESTAMP) or request.headers.get(HDR_TIMESTAMP.lower()),
    }
    ok, reason = check_inbound(WEBHOOK_HMAC_SECRET, headers, raw, tolerance_sec=300)
    if not ok:
        raise HTTPException(401, f"Invalid signature: {reason}")

    idem = x_idempotency_key or request.headers.get(HDR_IDEMPOTENCY) or request.headers.get(HDR_IDEMPOTENCY.lower())
    if _idem_seen(idem):
        return {"ok": True, "status": "duplicate_ignored"}

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

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.post(f"{TELEGRAM_API}/sendMessage", json=body)
        r.raise_for_status()
        return {"ok": True}






