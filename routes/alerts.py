# routes/alerts.py
from __future__ import annotations
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, Depends, Body, Header, HTTPException, Request
from pydantic import BaseModel, Field
import os, time

from utils.auth import require_api_key
from utils.telegram_api import send_message as telegram_send, get_me as telegram_get_me, send_chat_action as telegram_send_chat_action
from utils.hmac_utils import verify_inbound
from utils.approvals import preflight_proposal
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/alerts", tags=["Alerts"], dependencies=[Depends(require_api_key)])

WEBHOOK_HMAC_SECRET = os.getenv("WEBHOOK_HMAC_SECRET","").strip()
SINK_ENFORCE_APPROVALS = str(os.getenv("SINK_ENFORCE_APPROVALS","1")).lower() in ("1","true","yes","on")

# זיכרון מינימלי (אפשר להחליף ל-Redis)
_ACTIVE: Dict[str, Dict[str, Any]] = {}

class SendRequest(BaseModel):
    message: str = Field(..., min_length=1)
    parse_mode: Optional[str] = "Markdown"
    disable_preview: bool = True

class TradeAlert(BaseModel):
    symbol: str
    side: str = Field(..., pattern="^(?i)(LONG|SHORT)$")
    entry: float
    sl: float
    tp1: float
    tp2: float
    size_usd: float = 50
    note: str = ""
    quality: Optional[float] = None
    success_pct: Optional[float] = None

def format_trade_alert(symbol: str, side: str, entry: float, sl: float, tp1: float, tp2: float, size_usd: float,
                       note: str = "", quality: Optional[float] = None, success_pct: Optional[float] = None) -> str:
    lines = [
        "🔔 *AlgoGPT — Trade Alert*",
        f"*{symbol.upper()}* | *{side.upper()}*",
        f"Entry: `{entry:.6f}` | SL: `{sl:.6f}` | TP1: `{tp1:.6f}` | TP2: `{tp2:.6f}`",
        f"Size≈ ${size_usd:.2f}",
    ]
    if quality is not None:
        lines.append(f"Quality: `{quality:.2f}`")
    if success_pct is not None:
        lines.append(f"Success≈ `{success_pct:.1f}%`")
    if note:
        lines.append(f"Note: {note}")
    return "\n".join(lines)

async def send_telegram_alert(text: str, parse_mode: str = "Markdown", disable_preview: bool = True) -> Dict[str, Any]:
    return await telegram_send(text, parse_mode=parse_mode, disable_preview=disable_preview)

# == Service pings ==
@router.get("/ping")
async def ping(): return {"ok": True}

@router.get("/status")
async def status():
    me = await telegram_get_me()
    typing = await telegram_send_chat_action("typing")
    return {"ok": True, "getMe": me, "chatAction": typing}

@router.post("/test")
async def test():
    msg = "🔔 *AlgoGPT Alerts* — בדיקת בוט הצליחה.\nאם אתה רואה את זה בטלגרם, הכל תקין."
    res = await send_telegram_alert(msg)
    return {"ok": bool(res.get("ok")), "response": res}

@router.post("/send")
async def send(req: SendRequest = Body(...)):
    res = await send_telegram_alert(req.message, req.parse_mode or "Markdown", req.disable_preview)
    return {"ok": bool(res.get("ok")), "response": res}

# == Simple trade push ==
@router.post("/trade")
async def trade_alert(req: TradeAlert = Body(...)):
    text = format_trade_alert(
        req.symbol, req.side, req.entry, req.sl, req.tp1, req.tp2, req.size_usd,
        note=req.note, quality=req.quality, success_pct=req.success_pct
    )
    res = await send_telegram_alert(text)
    return {"ok": bool(res.get("ok")), "response": res, "text": text}

# == Sink APIs שהבוט משתמש בהם ==
@router.get("/trades/active")
async def trades_active():
    return {"ok": True, "items": list(_ACTIVE.values())}

class UpdateReq(BaseModel):
    trade_id: str
    updates: Dict[str, Any]

@router.post("/trades/update")
async def trades_update(req: UpdateReq):
    if req.trade_id not in _ACTIVE:
        return {"ok": False, "error": "not_found"}
    _ACTIVE[req.trade_id].update(req.updates or {})
    return {"ok": True, "item": _ACTIVE[req.trade_id]}

# ingest חתום HMAC מהבוט לאחר approve
@router.post("/trade-ingest")
async def trade_ingest(
    request: Request,
    x_signature: Optional[str] = Header(None, alias="X-Signature"),
    x_timestamp: Optional[str] = Header(None, alias="X-Timestamp"),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    if not WEBHOOK_HMAC_SECRET:
        raise HTTPException(400, "missing WEBHOOK_HMAC_SECRET")
    body = await request.body()
    if not verify_inbound(WEBHOOK_HMAC_SECRET, body, {"X-Signature": x_signature or "", "X-Timestamp": x_timestamp or ""}):
        raise HTTPException(401, "bad signature")

    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, "invalid json")

    # preflight נוסף בצד ה-sink (קשיח אם מופעל)
    pre = preflight_proposal({
        "symbol": data.get("symbol"),
        "side": data.get("side"),
        "entry": data.get("entry"),
        "sl": data.get("sl"),
        "tp1": data.get("tp1"),
        "leverage": data.get("leverage"),
        "success_pct": data.get("success_pct"),
        "budget": data.get("budget"),
        "interval": data.get("interval"),
    })
    if SINK_ENFORCE_APPROVALS and not pre["ok"]:
        return JSONResponse(
            status_code=422,
            content={"ok": False, "errors": pre["errors"], "warnings": pre.get("warnings", [])},
        )

    tid = str(data.get("trade_id") or "")
    if not tid:
        raise HTTPException(400, "missing trade_id")

    record = {
        "trade_id": tid,
        "symbol": data.get("symbol"),
        "side": data.get("side"),
        "current_price": data.get("current_price"),
        "entry": data.get("entry"),
        "sl": data.get("sl"),
        "tp1": data.get("tp1"),
        "tp2": data.get("tp2"),
        "tp3": data.get("tp3"),
        "leverage": data.get("leverage"),
        "success_pct": data.get("success_pct"),
        "interval": data.get("interval"),
        "market": data.get("market"),
        "time": int(time.time()),
        "status": "approved",
    }
    _ACTIVE[tid] = record

    # פרסום לטלגרם
    text = format_trade_alert(
        record["symbol"], record["side"], float(record["entry"]), float(record["sl"]),
        float(record["tp1"] or 0), float(record["tp2"] or 0), size_usd=float(data.get("budget") or 50.0),
        note=data.get("reason") or "approved", quality=None, success_pct=record.get("success_pct")
    )
    await send_telegram_alert(text)
    return {"ok": True, "item": record, "warnings": pre.get("warnings", [])}

@router.get("/analysis")
async def analysis(symbol: Optional[str] = None):
    return {"ok": True, "symbol": symbol, "note": "analysis endpoint stub"}





