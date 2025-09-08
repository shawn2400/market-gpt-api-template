# routes/analysis.py
from __future__ import annotations
import os, time, json, httpx
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, Depends, Body, Header, HTTPException
from pydantic import BaseModel, Field

from utils.auth import require_api_key
from utils.security import verify_hmac, idem_seen

router = APIRouter(prefix="/alerts", tags=["Alerts"], dependencies=[Depends(require_api_key)])

# ===== Env =====
BOT = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID_DEFAULT = os.getenv("TELEGRAM_CHAT_ID", "").strip()
TELEGRAM_API = f"https://api.telegram.org/bot{BOT}"
TIMEOUT = float(os.getenv("TELEGRAM_HTTP_TIMEOUT", "15"))

USE_REDIS_TRADES = os.getenv("USE_REDIS_TRADES", "0").lower() in ("1", "true", "yes")
if USE_REDIS_TRADES:
    import redis
    RED = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"), decode_responses=True)
else:
    _TRADES: Dict[str, Dict[str, Any]] = {}

# ===== Models =====
class TradeIn(BaseModel):
    trade_id: str = Field(..., min_length=4, max_length=64)
    symbol: str; side: str; current_price: float; leverage: int; entry: float; sl: float; tp1: float
    tp2: float | None = None; tp3: float | None = None; success_pct: float | None = None
    budget_usd: float | None = None; notional_usd: float | None = None; qty: float | None = None
    eta_sl: str | None = None; eta_tp1: str | None = None; eta_tp2: str | None = None; eta_tp3: str | None = None
    reason: str | None = None; chat_id: int | str | None = None

class TradeOut(BaseModel):
    ok: bool = True; trade_id: str; message_id: Optional[int] = None; chat_id: Optional[str | int] = None

class ActiveOut(BaseModel):
    ok: bool = True; count: int; items: List[Dict[str, Any]]

class UpdateReq(BaseModel):
    trade_id: str; updates: Dict[str, Any]

class AnalysisIn(BaseModel):
    chat_id: int | str; text: str; reply_to_message_id: Optional[int] = None; silent: Optional[bool] = True

# ===== Helpers =====
def _store_trade(item: Dict[str, Any]):
    if USE_REDIS_TRADES:
        RED.hset(f"trades:active:{item['trade_id']}", mapping=item)
        RED.sadd("trades:active:set", item["trade_id"])
    else:
        _TRADES[item["trade_id"]] = item

def _get_trade(tid: str): 
    return RED.hgetall(f"trades:active:{tid}") if USE_REDIS_TRADES else _TRADES.get(tid)

def _all_active() -> List[Dict[str, Any]]:
    if USE_REDIS_TRADES:
        return [RED.hgetall(f"trades:active:{tid}") for tid in RED.smembers("trades:active:set") if RED.hgetall(f"trades:active:{tid}")]
    return list(_TRADES.values())

def _update_trade(tid: str, **updates):
    if USE_REDIS_TRADES and RED.exists(f"trades:active:{tid}"):
        RED.hset(f"trades:active:{tid}", mapping=updates)
    elif tid in _TRADES: 
        _TRADES[tid].update(updates)

def _format_trade_message(rec: Dict[str, Any]) -> str:
    fmt = lambda x: f"{float(x):.6f}" if isinstance(x, (int, float)) else "—"
    lines = [
        f"🟢 *Trade Suggestion* #{rec['trade_id']}",
        f"*{rec['symbol']}* {rec['side']}  x{rec['leverage']}",
        f"Now: `{fmt(rec.get('current_price'))}`  Entry: `{fmt(rec.get('entry'))}`",
        f"SL: `{fmt(rec.get('sl'))}`  TP1: `{fmt(rec.get('tp1'))}`  TP2: `{fmt(rec.get('tp2'))}`  TP3: `{fmt(rec.get('tp3'))}`",
    ]
    if rec.get("success_pct"): lines.append(f"Success: *{float(rec['success_pct']):.1f}%*")
    if rec.get("notional_usd"): 
        lines.append(f"Budget: ${rec.get('budget_usd') or '—'}  Notional: ${float(rec['notional_usd']):.2f}  Qty: {fmt(rec.get('qty'))}")
    if rec.get("reason"): lines.append(f"_Reason_: {rec['reason']}")
    return "\n".join(lines)

def _approve_keyboard(trade_id: str) -> dict:
    return {"inline_keyboard": [[
        {"text": "✅ אישור ידני", "callback_data": f"approve:{trade_id}"},
        {"text": "🧠 ניתוח GPT", "callback_data": f"analysis:{trade_id}"},
        {"text": "🛑 דחייה", "callback_data": f"reject:{trade_id}"}
    ]]}

# ===== Routes =====
@router.post("/trade-ingest", response_model=TradeOut)
async def trade_ingest(payload: TradeIn = Body(...),
    x_idempotency_key: Optional[str] = Header(default=None),
    x_signature: Optional[str] = Header(default=None)):
    if not BOT: raise HTTPException(500, "TELEGRAM_BOT_TOKEN not configured")
    raw = json.dumps(payload.model_dump(), separators=(",", ":"), ensure_ascii=False).encode()
    if not verify_hmac(x_signature, raw): raise HTTPException(401, "Invalid signature")
    if x_idempotency_key and idem_seen(x_idempotency_key):
        rec = _get_trade(payload.trade_id) or {}
        return TradeOut(ok=True, trade_id=payload.trade_id, message_id=int(rec.get("message_id") or 0) or None, chat_id=rec.get("chat_id"))
    rec = payload.model_dump()
    rec.update({"status": "active", "ts": int(time.time()),
                "hits": json.dumps({"tp1": False,"tp2": False,"tp3": False,"sl": False}),
                "near": json.dumps({"tp1": False,"tp2": False,"tp3": False,"sl": False})})
    txt = _format_trade_message(rec)
    body = {"chat_id": payload.chat_id or CHAT_ID_DEFAULT, "text": txt,
            "parse_mode": "Markdown", "disable_web_page_preview": True,
            "reply_markup": _approve_keyboard(payload.trade_id)}
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.post(f"{TELEGRAM_API}/sendMessage", json=body); r.raise_for_status()
        msg = r.json().get("result", {})
        rec["chat_id"], rec["message_id"] = body["chat_id"], msg.get("message_id")
        _store_trade(rec)
        return TradeOut(ok=True, trade_id=payload.trade_id, message_id=rec["message_id"], chat_id=rec["chat_id"])

@router.get("/trades/active", response_model=ActiveOut)
def trades_active(): 
    items = _all_active(); return ActiveOut(ok=True, count=len(items), items=items)

@router.post("/trades/update", response_model=dict)
def trades_update(payload: UpdateReq): 
    _update_trade(payload.trade_id, **payload.updates); return {"ok": True}

@router.post("/analysis", response_model=dict)
async def analysis_ingest(payload: AnalysisIn = Body(...),
    x_idempotency_key: Optional[str] = Header(default=None),
    x_signature: Optional[str] = Header(default=None)):
    raw = json.dumps(payload.model_dump(), separators=(",", ":"), ensure_ascii=False).encode()
    if not verify_hmac(x_signature, raw): raise HTTPException(401, "Invalid signature")
    if x_idempotency_key and idem_seen(x_idempotency_key): return {"ok": True, "status": "duplicate_ignored"}
    if not BOT: raise HTTPException(500, "TELEGRAM_BOT_TOKEN not configured")
    body = {"chat_id": payload.chat_id, "text": payload.text,
            "parse_mode": "Markdown", "disable_web_page_preview": True}
    if payload.reply_to_message_id: body["reply_to_message_id"] = payload.reply_to_message_id
    if payload.silent: body["disable_notification"] = True
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.post(f"{TELEGRAM_API}/sendMessage", json=body); r.raise_for_status()
        return {"ok": True}











































