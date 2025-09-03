# routes/alerts.py
from __future__ import annotations
from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, Body, Header, HTTPException, Request
from pydantic import BaseModel, Field, constr
import os, time

from utils.auth import require_api_key
from utils.telegram_api import (
    send_message as telegram_send,
    get_me as telegram_get_me,
    send_chat_action as telegram_send_chat_action,
)
from utils.hmac_utils import verify_inbound
from utils.approvals import preflight_proposal
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/alerts", tags=["Alerts"], dependencies=[Depends(require_api_key)])

WEBHOOK_HMAC_SECRET = os.getenv("WEBHOOK_HMAC_SECRET", "").strip()
SINK_ENFORCE_APPROVALS = str(os.getenv("SINK_ENFORCE_APPROVALS", "1")).lower() in ("1", "true", "yes", "on")

# זיכרון מקומי — מומלץ להחליף ל־Redis בפרודקשן
_ACTIVE: Dict[str, Dict[str, Any]] = {}

class SendRequest(BaseModel):
    message: str = Field(..., min_length=1)
    parse_mode: Optional[str] = "Markdown"
    disable_preview: bool = True

class TradeAlert(BaseModel):
    symbol: str
    side: constr(pattern=r"^(?i:LONG|SHORT)$") = Field(...)
    entry: float
    sl: float
    tp1: float
    tp2: Optional[float] = None
    tp3: Optional[float] = None
    size_usd: float = 50
    note: str = ""
    quality: Optional[float] = None
    success_pct: Optional[float] = None

def format_trade_alert(
    symbol: str, side: str, entry: float, sl: float, tp1: float,
    tp2: Optional[float] = None, tp3: Optional[float] = None,
    size_usd: float = 50.0, *, note: str = "",
    quality: Optional[float] = None, success_pct: Optional[float] = None,
) -> str:
    parts = [
        "🔔 *AlgoGPT — Trade Alert*",
        f"*{symbol.upper()}* | *{side.upper()}*",
        f"Entry: `{entry:.6f}` | SL: `{sl:.6f}` | TP1: `{tp1:.6f}`",
    ]
    if tp2 is not None:
        parts[-1] += f" | TP2: `{tp2:.6f}`"
    if tp3 is not None:
        parts[-1] += f" | TP3: `{tp3:.6f}`"

    parts.append(f"Size≈ ${size_usd:.2f}")
    if quality is not None:
        parts.append(f"Quality: `{quality:.2f}`")
    if success_pct is not None:
        parts.append(f"Success≈ `{success_pct:.1f}%`")
    if note:
        parts.append(f"Note: {note}")
    return "\n".join(parts)

async def send_telegram_alert(text: str, parse_mode="Markdown", disable_preview=True) -> Dict[str, Any]:
    return await telegram_send(text, parse_mode=parse_mode, disable_preview=disable_preview)

# == Service endpoints ==
@router.get("/ping")
async def ping() -> Dict[str, Any]:
    return {"ok": True}

@router.get("/status")
async def status() -> Dict[str, Any]:
    me = await telegram_get_me()
    typing = await telegram_send_chat_action("typing")
    return {"ok": True, "getMe": me, "chatAction": typing}

@router.post("/test")
async def test() -> Dict[str, Any]:
    msg = "🔔 *AlgoGPT Alerts* — בדיקת בוט הצליחה.\nאם אתה רואה את זה בטלגרם, הכל תקין."
    res = await send_telegram_alert(msg)
    return {"ok": bool(res.get("ok")), "response": res}

@router.post("/send")
async def send(req: SendRequest = Body(...)) -> Dict[str, Any]:
    res = await send_telegram_alert(req.message, req.parse_mode or "Markdown", req.disable_preview)
    return {"ok": bool(res.get("ok")), "response": res}

# == Simple trade push ==
@router.post("/trade")
async def trade_alert(req: TradeAlert = Body(...)) -> Dict[str, Any]:
    text = format_trade_alert(
        req.symbol, req.side, req.entry, req.sl, req.tp1,
        req.tp2, req.tp3, req.size_usd,
        note=req.note, quality=req.quality, success_pct=req.success_pct
    )
    res = await send_telegram_alert(text)
    return {"ok": bool(res.get("ok")), "response": res, "text": text}

# == Sink APIs (לטלגרם) ==
@router.get("/trades/active")
async def trades_active() -> Dict[str, Any]:
    return {"ok": True, "items": list(_ACTIVE.values())}

class UpdateReq(BaseModel):
    trade_id: str
    updates: Dict[str, Any]

@router.post("/trades/update")
async def trades_update(req: UpdateReq) -> Dict[str, Any]:
    if req.trade_id not in _ACTIVE:
        return {"ok": False, "error": "not_found"}
    _ACTIVE[req.trade_id].update(req.updates or {})
    return {"ok": True, "item": _ACTIVE[req.trade_id]}

@router.post("/trade-ingest")
async def trade_ingest(
    request: Request,
    x_signature: Optional[str] = Header(None, alias="X-Signature"),
    x_timestamp: Optional[str] = Header(None, alias="X-Timestamp"),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> JSONResponse | Dict[str, Any]:
    if not WEBHOOK_HMAC_SECRET:
        raise HTTPException(400, "missing WEBHOOK_HMAC_SECRET")

    body = await request.body()
    if not verify_inbound(WEBHOOK_HMAC_SECRET, body, {"X-Signature": x_signature or "", "X-Timestamp": x_timestamp or ""}):
        raise HTTPException(401, "bad signature")

    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, "invalid json")

    # Preflight
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
        record["symbol"], record["side"],
        float(record["entry"]), float(record["sl"]), float(record["tp1"] or 0),
        (float(record["tp2"]) if record.get("tp2") else None),
        (float(record["tp3"]) if record.get("tp3") else None),
        size_usd=float(data.get("budget") or 50.0),
        note=data.get("reason") or "approved",
        quality=None,
        success_pct=record.get("success_pct"),
    )
    await send_telegram_alert(text)
    return {"ok": True, "item": record, "warnings": pre.get("warnings", [])}

@router.get("/analysis")
async def analysis(symbol: Optional[str] = None) -> Dict[str, Any]:
    return {"ok": True, "symbol": symbol, "note": "analysis endpoint stub"}








