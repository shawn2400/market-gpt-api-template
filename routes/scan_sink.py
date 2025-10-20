# routes/scan_sink.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import os, time, json
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Request, Header
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field, validator

from utils.redis_helper import set_json
from utils.signature import verify_signed

router = APIRouter(prefix="/alerts/trades", tags=["Public Feed"])

API_BEARER_TOKEN = (os.getenv("API_BEARER_TOKEN") or os.getenv("API_TOKEN") or "").strip()
REQUIRE_AUTH = (os.getenv("SCAN_SINK_REQUIRE_AUTH", "1").lower() in ("1","true","yes","on"))
DEFAULT_TTL = int(os.getenv("SCAN_TTL_SEC", "900"))

# --------- מודלים ---------
class ItemTopK(BaseModel):
    symbol: str
    side: str
    score: float
    reason: Optional[str] = ""
    timeframe: Optional[str] = "15m"
    ts: Optional[int] = None

    @validator("symbol")
    def _sym(cls, v): return v.upper()

    @validator("side")
    def _side(cls, v):
        v = (v or "").upper()
        return "BUY" if v == "BUY" else "SELL"

class ItemNow(BaseModel):
    symbol: str
    side: str
    price: float
    reason: Optional[str] = ""
    timeframe: Optional[str] = "15m"
    ts: Optional[int] = None

    @validator("symbol")
    def _sym(cls, v): return v.upper()

    @validator("side")
    def _side(cls, v):
        v = (v or "").upper()
        return "BUY" if v == "BUY" else "SELL"

class ScanUpdate(BaseModel):
    topk: Optional[List[ItemTopK]] = Field(default=None, description="Optional TopK list")
    now:  Optional[List[ItemNow]]  = Field(default=None, description="Optional Now list")
    ttl_sec: Optional[int] = Field(default=None)

# --------- עזרי אבטחה ---------
def _bearer_ok(h: Optional[str]) -> bool:
    if not REQUIRE_AUTH:
        return True
    if not API_BEARER_TOKEN:
        return False
    return bool(h and h.startswith("Bearer ") and h.split(" ", 1)[1].strip() == API_BEARER_TOKEN)

# --------- REST: עדכון רשימות (TopK/Now) ---------
@router.post("/update")
async def scan_update(
    req: Request,
    authorization: Optional[str] = Header(None, alias="Authorization"),
    x_ts: Optional[str] = Header(None, alias="X-Ts"),
    x_sig: Optional[str] = Header(None, alias="X-Signature"),
):
    raw = await req.body()
    # אימות Bearer (אם נדרש)
    if REQUIRE_AUTH and not _bearer_ok(authorization):
        # אם נכשל Bearer, ננסה חתימה (HMAC) — קביל גם בלי Bearer
        if not (x_ts and x_sig and verify_signed(x_ts, raw, x_sig)):
            return PlainTextResponse("Unauthorized", status_code=401)

    # אימות חתימה (אם יש כותרות) — שומר על backwards compat לנתיבים ציבוריים חתומים
    if x_ts and x_sig and not verify_signed(x_ts, raw, x_sig):
        return JSONResponse({"ok": False, "detail": "Bad signature"}, status_code=400)

    try:
        payload = ScanUpdate.parse_raw(raw)
    except Exception as e:
        return JSONResponse({"ok": False, "detail": f"invalid payload: {e}"}, status_code=400)

    ttl = int(payload.ttl_sec or DEFAULT_TTL)
    now_ts = int(time.time())

    # TopK
    if payload.topk is not None:
        items = [dict(**i.dict(), ts=int(i.ts or now_ts)) for i in payload.topk]
        await set_json("scan:topk", {"items": items, "ts": now_ts}, ttl_sec=ttl)

    # Now
    if payload.now is not None:
        items = [dict(**i.dict(), ts=int(i.ts or now_ts)) for i in payload.now]
        await set_json("scan:now", {"items": items, "ts": now_ts}, ttl_sec=ttl)

    return JSONResponse({"ok": True, "ts": now_ts})
