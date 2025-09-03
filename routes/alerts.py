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

_ACTIVE: Dict[str, Dict[str, Any]] = {}  # Memory only

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
    if tp2: parts[-1] += f" | TP2: `{tp2:.6f}`"
    if tp3: parts[-1] += f" | TP3: `{tp3:.6f}`"
    parts.append(f"Size≈ ${size_usd:.2f}")
    if quality: parts.append(f"Quality: `{quality:.2f}`")
    if success_pct: parts.append(f"Success≈ `{success_pct:.1f}%`")
    if note: parts.append(f"Note: {note}")
    return "\n".join(parts)

async def send_telegram_alert(text: str, parse_mode="Markdown", disable_preview=True) -> Dict[str, Any]:
    return await telegram_send(text, parse_mode=parse_mode, disable_preview=disable_preview)

# --- routes (ping, status, test, send, trade, ingest) נשארו כפי ששלחת --- #








