# routes/trade_sink.py
from __future__ import annotations
from fastapi import APIRouter, Depends, Body, Header, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
import os, time, json, httpx

# אבטחה
try:
    from utils.auth import require_api_key
except Exception:
    def require_api_key():
        return None

from utils.security import verify_hmac, idem_seen

router = APIRouter(prefix="/alerts", tags=["Alerts"], dependencies=[Depends(require_api_key)])

BOT = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID_DEFAULT = os.getenv("TELEGRAM_CHAT_ID", "").strip()
TELEGRAM_API = f"https://api.telegram.org/bot{BOT}"
TIMEOUT = float(os.getenv("TELEGRAM_HTTP_TIMEOUT", "15"))

USE_REDIS_TRADES = os.getenv("USE_REDIS_TRADES","0").lower() in ("1","true","yes")
if USE_REDIS_TRADES:
    import redis
    RED = redis.from_url(os.getenv("REDIS_URL","redis://localhost:6379"), decode_responses=True)
else:
    _TRADES: Dict[str, Dict[str, Any]] = {}   # trade_id -> record

class TradeIn(BaseModel):
    trade_id: str = Field(..., min_length=4, max_length=64)
    symbol: str
    side: str
    current_price: float
    leverage: int
    entry: float
    sl: float
    tp1: float
    tp2: float | None = None
    tp3: float | None = None
    success_pct: float | None = None
    budget_usd: float | None = None
    notional_usd: float | None = None
    qty: float | None = None
    eta_sl: str | None = None
    eta_tp1: str | None = None
    eta_tp2: str | None = None
    eta_tp3: str | None = None
    reason: str | None = None
    chat_id: int | str | None = None

class TradeOut(BaseModel):
    ok: bool = True
    trade_id: str
    message_id: Optional[int] = None
    chat_id: Optional[str | int] = None

def _store_trade(item: Dict[str, Any]):
    if USE_REDIS_TRADES:
        RED.hset(f"trades:active:{item['trade_id']}", mapping=item)
        RED.sadd("trades:active:set", item["trade_id"])
    else:
        _TRADES[item["trade_id"]] = item

def _get_trade(tid: str) -> Optional[Dict[str, Any]]:
    if USE_REDIS_TRADES:
        data = RED.hgetall(f"trades:active:{tid}")
        return data or None
    return _TRADES.get(tid)

def _all_active() -> List[Dict[str, Any]]:
    if USE_REDIS_TRADES:
        tids = RED.smembers("trades:active:set") or []
        out = []
        for tid in tids:
            d = RED.hgetall(f"trades:active:{tid}")
            if d: out.append(d)
        return out
    return list(_TRADES.values())

def _update_trade(tid: str, **updates):
    if USE_REDIS_TRADES:
        key = f"trades:active:{tid}"
        if not RED.exists(key): return
        RED.hset(key, mapping=updates)
    else:
        if tid in _TRADES:
            _TRADES[tid].update(updates)

def _format_trade_message(rec: Dict[str, Any]) -> str:
    fmt = lambda x: f"{float(x):.6f}" if isinstance(x,(int,float)) else "—"
    lines = [
        f"🟢 *Trade Suggestion* #{rec['trade_id']}",
        f"*{rec['symbol']}* {rec['side']}  x{rec['leverage']}",
        f"Now: `{fmt(rec.get('current_price'))}`  Entry: `{fmt(rec.get('entry'))}`",
        f"SL: `{fmt(rec.get('sl'))}`  TP1: `{fmt(rec.get('tp1'))}`  TP2: `{fmt(rec.get('tp2'))}`  TP3: `{fmt(rec.get('tp3'))}`",
    ]
    if rec.get("success_pct") is not None:
        lines.append(f"Success: *{float(rec['success_pct']):.1f}%*")
    if rec.get("notional_usd"):
        lines.append(f"Budget: ${rec.get('budget_usd') or '—'}  Notional: ${float(rec['notional_usd']):.2f}  Qty: {fmt(rec.get('qty'))}")
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
        # דופליקט מהרשת – החזר OK ללא שליחה שנייה
        rec = _get_trade(payload.trade_id) or {}
        return TradeOut(ok=True, trade_id=payload.trade_id, message_id=int(rec.get("message_id") or 0) or None, chat_id=rec.get("chat_id"))

    rec = payload.model_dump()
    rec.update({
        "status":"active",
        "ts": int(time.time()),
        "hits": json.dumps({"tp1":False,"tp2":False,"tp3":False,"sl":False}),
        "near": json.dumps({"tp1":False,"tp2":False,"tp3":False,"sl":False}),
    })
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

# --- ממשק לוורקר המעקב (Watchdog) ---
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




