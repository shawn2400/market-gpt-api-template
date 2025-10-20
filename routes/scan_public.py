# routes/scan_public.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse

router = APIRouter(prefix="/scan", tags=["Public Feed"])

# ---- Rate-limit (נפילה רכה אם אין מודול) ----
try:
    from utils.rate_limit_tb import tb_allow  # type: ignore
except Exception:
    async def tb_allow(ip: str, path: str, sse_hint: bool = False):
        return True, None

# ---- Redis async (נפילה רכה אם אין) ----
try:
    import redis.asyncio as aioredis  # type: ignore
except Exception:
    aioredis = None  # type: ignore

NS = os.getenv("REDIS_NAMESPACE", "ops-supervisor-web").strip() or "ops-supervisor-web"
REDIS_URL = (os.getenv("REDIS_URL") or "").strip()
PUBLIC_TOPK_K = os.getenv("PUBLIC_TOPK_KEY", f"{NS}:public:topk")
PUBLIC_NOW_K  = os.getenv("PUBLIC_NOW_KEY",  f"{NS}:public:now")

# פולינג ל-SSE
STREAM_INTERVAL_SEC = int(os.getenv("PUBLIC_STREAM_INTERVAL_SEC", "3") or 3)
FAPI = os.getenv("BINANCE_FAPI", "https://fapi.binance.com").rstrip("/")

# אם אין Redis — fallback מינימלי בזיכרון
_mem_store: Dict[str, Any] = {
    "topk": {"items": [], "ts": int(time.time())},
    "now": {"items": [], "ts": int(time.time())},
}

# --- עזרי IO ---
async def _get_redis():
    if not (aioredis and REDIS_URL):
        return None
    r = getattr(router, "_r", None)
    if r:
        return r
    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    setattr(router, "_r", r)
    return r

def _http() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=10.0, headers={"User-Agent": "algogpt/public-scan"})

def _client_ip(request: Request) -> str:
    if os.getenv("TRUST_XFF", "0").lower() in ("1", "true", "yes", "on"):
        xff = request.headers.get("x-forwarded-for") or ""
        if xff:
            return xff.split(",")[0].strip()
    return request.client.host if request.client else "0.0.0.0"

# --- קריאת נתוני TopK/Now מ-Redis או מהזיכרון ---
async def _load_json_from_redis(key: str) -> Optional[Dict[str, Any]]:
    r = await _get_redis()
    if not r:
        return None
    try:
        raw = await r.get(key)
        if not raw:
            return None
        obj = json.loads(raw)
        if isinstance(obj, dict):
            return obj
    except Exception:
        return None
    return None

def _mem_get(kind: str) -> Dict[str, Any]:
    rec = _mem_store.get(kind) or {}
    return {"ok": True, "items": list(rec.get("items") or []), "ts": int(rec.get("ts") or time.time())}

async def _ensure_sample_mem(kind: str):
    # ממלא מעט דמו אם אין Redis — כדי שהדף לא יהיה ריק
    rec = _mem_store.get(kind) or {}
    if not rec.get("items"):
        now = int(time.time())
        if kind == "topk":
            rec = {
                "items": [
                    {"symbol": "BTCUSDT", "side": "BUY",  "score": 8.7, "reason": "ADX↑, breakout", "timeframe": "15m", "ts": now},
                    {"symbol": "ETHUSDT", "side": "SELL", "score": 7.9, "reason": "RSI div",        "timeframe": "5m",  "ts": now},
                ],
                "ts": now,
            }
        else:
            rec = {
                "items": [
                    {"symbol": "BTCUSDT", "side": "BUY", "price": 63000.0, "reason": "mark", "timeframe": "1m", "ts": now},
                    {"symbol": "ETHUSDT", "side": "BUY", "price": 3200.0,  "reason": "mark", "timeframe": "1m", "ts": now},
                ],
                "ts": now,
            }
        _mem_store[kind] = rec

# --- Binance עזר: משיכת mark prices לרשימה (אם תרצה להזין NOW בזמן אמת) ---
async def _fetch_mark_prices(symbols: List[str]) -> Dict[str, float]:
    if not symbols:
        return {}
    url = f"{FAPI}/fapi/v1/premiumIndex"
    out: Dict[str, float] = {}
    async with _http() as c:
        for s in symbols:
            try:
                r = await c.get(url, params={"symbol": s})
                if r.status_code == 200:
                    j = r.json()
                    mp = float(j.get("markPrice"))
                    out[s] = mp
            except Exception:
                continue
    return out

# --- Endpoints JSON ---
@router.get("/public-topk")
async def public_topk(request: Request):
    ip = _client_ip(request)
    allowed, ra = await tb_allow(ip, request.url.path, sse_hint=False)
    if not allowed:
        resp = JSONResponse({"ok": False, "error": "rate_limited"}, status_code=429)
        if ra:
            resp.headers["Retry-After"] = str(ra)
        return resp

    obj = await _load_json_from_redis(PUBLIC_TOPK_K)
    if obj is None:
        await _ensure_sample_mem("topk")
        return _mem_get("topk")
    # מצפים לפורמט {"items":[...], "ts": unix}
    items = obj.get("items") or []
    ts = int(obj.get("ts") or time.time())
    return {"ok": True, "items": items, "ts": ts}

@router.get("/public-now")
async def public_now(request: Request):
    ip = _client_ip(request)
    allowed, ra = await tb_allow(ip, request.url.path, sse_hint=False)
    if not allowed:
        resp = JSONResponse({"ok": False, "error": "rate_limited"}, status_code=429)
        if ra:
            resp.headers["Retry-After"] = str(ra)
        return resp

    obj = await _load_json_from_redis(PUBLIC_NOW_K)
    if obj is None:
        await _ensure_sample_mem("now")
        return _mem_get("now")
    items = obj.get("items") or []
    ts = int(obj.get("ts") or time.time())
    return {"ok": True, "items": items, "ts": ts}

# --- SSE stream: משדר אירועים בשם "topk" ו-"now" כאשר יש שינוי / כל N שניות ---
@router.get("/public-stream")
async def public_stream(request: Request, authorization: Optional[str] = Header(None, alias="Authorization")):
    ip = _client_ip(request)
    allowed, ra = await tb_allow(ip, request.url.path, sse_hint=True)
    if not allowed:
        resp = PlainTextResponse("rate_limited", status_code=429)
        if ra:
            resp.headers["Retry-After"] = str(ra)
        return resp

    async def _gen():
        # מצב אחרון ששודר (לזיהוי שינוי)
        last_topk = ""
        last_now = ""
        # קצב שידור
        interval = max(1, int(STREAM_INTERVAL_SEC))

        # שליחת אירוע פתיחה (ידידותי ללקוח)
        yield "event: ping\ndata: {}\n\n"

        while True:
            if await request.is_disconnected():
                break

            # TOPK
            obj_t = await _load_json_from_redis(PUBLIC_TOPK_K)
            if obj_t is None:
                await _ensure_sample_mem("topk")
                obj_t = _mem_store["topk"]
            try:
                payload_t = json.dumps(
                    {"items": obj_t.get("items") or [], "ts": int(obj_t.get("ts") or time.time())},
                    separators=(",", ":"),
                    ensure_ascii=False,
                )
            except Exception:
                payload_t = '{"items":[],"ts":%d}' % int(time.time())

            if payload_t != last_topk:
                last_topk = payload_t
                yield "event: topk\n"
                yield f"data: {payload_t}\n\n"

            # NOW
            obj_n = await _load_json_from_redis(PUBLIC_NOW_K)
            if obj_n is None:
                await _ensure_sample_mem("now")
                obj_n = _mem_store["now"]
            try:
                payload_n = json.dumps(
                    {"items": obj_n.get("items") or [], "ts": int(obj_n.get("ts") or time.time())},
                    separators=(",", ":"),
                    ensure_ascii=False,
                )
            except Exception:
                payload_n = '{"items":[],"ts":%d}' % int(time.time())

            if payload_n != last_now:
                last_now = payload_n
                yield "event: now\n"
                yield f"data: {payload_n}\n\n"

            # דופק כל interval שניות
            await asyncio.sleep(interval)

    headers = {
        "Cache-Control": "no-store",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    }
    return StreamingResponse(_gen(), media_type="text/event-stream", headers=headers)

