# routes/public.py
from __future__ import annotations
import os, json, time, hashlib, logging, asyncio
from typing import Any, Dict, List, Optional, AsyncIterator, Iterable
from fastapi import APIRouter, Query, Header, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

logger = logging.getLogger("algogpt.public")
router = APIRouter(tags=["Public Feed"])

# === Env / Config ===
NS = os.getenv("REDIS_NAMESPACE", "ops-supervisor-web").strip() or "ops-supervisor-web"
REDIS_URL = (os.getenv("REDIS_URL") or "").strip()
PUBLIC_CACHE_MAX_AGE = int(os.getenv("PUBLIC_CACHE_MAX_AGE", "20") or "20")
PUBLIC_REQUIRE_BEARER = os.getenv("PUBLIC_REQUIRE_BEARER", "0").lower() in ("1", "true", "yes", "on")
API_BEARER_TOKEN = (os.getenv("API_BEARER_TOKEN") or os.getenv("API_TOKEN") or "").strip()
SSE_HEARTBEAT_SEC = int(os.getenv("PUBLIC_SSE_HEARTBEAT_SEC", "20") or "20")
SSE_MAX_IDLE_SEC = int(os.getenv("PUBLIC_SSE_MAX_IDLE_SEC", "300") or "300")  # חותך חיבור שלא קיבל כלום הרבה זמן
PUBSUB_CHANNEL = f"{NS}:public:events"  # מצופה: הודעות מסוג {"type": "now"|"topk", "ts": ...}

# === Redis (async) ===
_aioredis = None
try:
    import redis.asyncio as _aioredis  # type: ignore
except Exception:
    _aioredis = None

_redis_client = None
_client_lock = asyncio.Lock()

async def _get_redis():
    """Lazy singleton with retries suppressed (לא שוברים את השרת אם אין Redis)."""
    global _redis_client
    if not (_aioredis and REDIS_URL):
        return None
    if _redis_client:
        return _redis_client
    async with _client_lock:
        if _redis_client:
            return _redis_client
        try:
            _redis_client = _aioredis.from_url(REDIS_URL, decode_responses=True)
        except Exception as e:
            logger.warning("public: redis connect failed: %s", e)
            _redis_client = None
    return _redis_client

# === Security (optional Bearer) ===
def _bearer_ok(auth_header: Optional[str]) -> bool:
    if not PUBLIC_REQUIRE_BEARER:
        return True
    if not API_BEARER_TOKEN:
        # דרשת Bearer דלוקה אבל אין טוקן — נחסום כדי לא לחשוף פיד
        return False
    if not (auth_header and auth_header.startswith("Bearer ")):
        return False
    return auth_header.split(" ", 1)[1].strip() == API_BEARER_TOKEN

def _deny_unauth():
    raise HTTPException(status_code=401, detail="Unauthorized")

# === Helpers ===
def _json_md5(obj: Any) -> str:
    try:
        body = json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
        return hashlib.md5(body).hexdigest()
    except Exception:
        return hashlib.md5(b"{}").hexdigest()

async def _read_json(key: str) -> Optional[Any]:
    r = await _get_redis()
    if not r:
        return None
    try:
        raw = await r.get(key)
        if not raw:
            return None
        return json.loads(raw)
    except Exception as e:
        logger.debug("public: read_json fail: %s", e)
        return None

def _symbols_param_to_set(symbols: Optional[str]) -> Optional[set]:
    if not symbols:
        return None
    s = [x.strip().upper() for x in symbols.split(",") if x.strip()]
    return set(s) if s else None

def _filter_topk(items: List[Dict[str, Any]],
                 k: int,
                 min_score: Optional[float],
                 side: Optional[str],
                 symbols_set: Optional[set]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    sside = (side or "").upper()
    for it in items:
        try:
            if symbols_set and str(it.get("symbol","")).upper() not in symbols_set:
                continue
            if sside in ("BUY", "SELL"):
                if str(it.get("side","")).upper() != sside:
                    continue
            if min_score is not None:
                try:
                    if float(it.get("score", 0.0)) < float(min_score):
                        continue
                except Exception:
                    continue
            out.append(it)
            if len(out) >= k:
                break
        except Exception:
            continue
    return out

def _filter_now(items: List[Dict[str, Any]],
                symbols_set: Optional[set]) -> List[Dict[str, Any]]:
    if not symbols_set:
        return items
    out: List[Dict[str, Any]] = []
    for it in items:
        try:
            if str(it.get("symbol","")).upper() in symbols_set:
                out.append(it)
        except Exception:
            continue
    return out

def _json_response(payload: Dict[str, Any], etag: Optional[str] = None) -> JSONResponse:
    resp = JSONResponse(payload)
    # אל תבטל את המידלוואר שלך; רק תוסיף Cache-Control מפורש
    resp.headers.setdefault("Cache-Control", f"public, max-age={PUBLIC_CACHE_MAX_AGE}")
    if etag:
        resp.headers.setdefault("ETag", f"\"{etag}\"")
    return resp

# === Endpoints ===

@router.get("/scan/public-now")
async def public_now(
    symbols: Optional[str] = Query(None, description="comma-separated symbols filter, e.g. BTCUSDT,ETHUSDT"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    if not _bearer_ok(authorization):
        _deny_unauth()

    obj = await _read_json(f"{NS}:public:now")
    if not obj:
        obj = {"ts": int(time.time()), "items": []}  # אין Redis / אין נתונים — לא שוברים, רק ריק
    items = obj.get("items") or []
    filt = _filter_now(items, _symbols_param_to_set(symbols))
    out = {"ok": True, "ts": int(obj.get("ts") or time.time()), "items": filt}
    etag = _json_md5(out)
    return _json_response(out, etag=etag)

@router.get("/scan/public-topk")
async def public_topk(
    k: int = Query(5, ge=1, le=50),
    min_score: Optional[float] = Query(None, ge=0.0),
    side: Optional[str] = Query(None, pattern="^(?i)(buy|sell)$"),
    symbols: Optional[str] = Query(None, description="comma-separated symbols filter"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    if not _bearer_ok(authorization):
        _deny_unauth()

    obj = await _read_json(f"{NS}:public:topk")
    if not obj:
        payload = {"ok": True, "ts": int(time.time()), "k": k, "items": []}
        return _json_response(payload, etag=_json_md5(payload))

    items = obj.get("items") or []
    if not isinstance(items, list):
        items = []
    items = _filter_topk(items, k=k, min_score=min_score, side=side, symbols_set=_symbols_param_to_set(symbols))
    out = {
        "ok": True,
        "ts": int(obj.get("ts") or time.time()),
        "k": min(k, len(items)),
        "items": items[:k],
    }
    etag = _json_md5(out)
    return _json_response(out, etag=etag)

# --- Snapshot קומפקטי ללקוחות קריטיים (ללא סינון) ---
@router.get("/scan/public-topk/snapshot")
async def public_topk_snapshot(
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    if not _bearer_ok(authorization):
        _deny_unauth()
    obj = await _read_json(f"{NS}:public:topk") or {"ts": int(time.time()), "items": []}
    out = {"ok": True, "ts": int(obj.get("ts") or time.time()), "k": int(obj.get("k") or len(obj.get("items") or [])), "items": obj.get("items") or []}
    return _json_response(out, etag=_json_md5(out))

# === SSE (Server-Sent Events) חי מ-Redis Pub/Sub ===
async def _sse_iter(last_event_id: Optional[str]) -> AsyncIterator[bytes]:
    """
    מאזין ל-PUBSUB על הערוץ NS:public:events ומזרים אירועי now/topk.
    פורמט הודעה רצוי (JSON):
      {"type":"now","ts":1699999999} או {"type":"topk","ts":1699999999}
    - שולח heartbeat כל SSE_HEARTBEAT_SEC.
    - סוגר חיבור אם לא קיבל דבר במשך SSE_MAX_IDLE_SEC (חסכון משאבים).
    """
    r = await _get_redis()
    started = time.time()
    last_sent = time.time()

    # helper: שליחת אירוע
    async def send_event(event: str, data: Dict[str, Any]):
        nonlocal last_sent
        body = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        # event: <type>\nid: <ts>\ndata: <json>\n\n
        eid = str(int(data.get("ts") or time.time()))
        chunk = f"event: {event}\nid: {eid}\ndata: {body}\n\n".encode("utf-8")
        last_sent = time.time()
        return chunk

    # שליחת סנאפשוט ראשון (מפחית זמן עדכון ללקוח)
    try:
        now_obj = await _read_json(f"{NS}:public:now") or {"ts": int(time.time()), "items": []}
        yield await send_event("now", {"ts": int(now_obj.get("ts") or time.time()), "items": now_obj.get("items") or []})
    except Exception:
        pass
    try:
        topk_obj = await _read_json(f"{NS}:public:topk") or {"ts": int(time.time()), "items": [], "k": 0}
        yield await send_event("topk", {"ts": int(topk_obj.get("ts") or time.time()), "k": int(topk_obj.get("k") or len(topk_obj.get("items") or [])), "items": topk_obj.get("items") or []})
    except Exception:
        pass

    # אם אין Redis – נעשה רק heartbeat עד ניתוק (לא שוברים קוד)
    if not r:
        while True:
            await asyncio.sleep(SSE_HEARTBEAT_SEC)
            if time.time() - last_sent > SSE_MAX_IDLE_SEC:
                break
            yield b": keep-alive\n\n"
        return

    pubsub = r.pubsub(ignore_subscribe_messages=True)
    try:
        await pubsub.subscribe(PUBSUB_CHANNEL)
        while True:
            # בדיקת הודעה עם timeout קצר (לא לחסום)
            msg = None
            try:
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            except Exception:
                msg = None

            # heartbeat / idle cutoff
            now = time.time()
            if now - last_sent >= SSE_HEARTBEAT_SEC:
                yield b": keep-alive\n\n"
                last_sent = now
            if now - started > SSE_MAX_IDLE_SEC:
                break

            if not msg:
                continue

            try:
                payload = msg.get("data")
                if not isinstance(payload, str):
                    continue
                data = json.loads(payload)
                etype = str(data.get("type") or "").lower()
                if etype not in ("now", "topk"):
                    continue

                if etype == "now":
                    obj = await _read_json(f"{NS}:public:now") or {"ts": int(time.time()), "items": []}
                    yield await send_event("now", {"ts": int(obj.get("ts") or time.time()), "items": obj.get("items") or []})
                else:
                    obj = await _read_json(f"{NS}:public:topk") or {"ts": int(time.time()), "items": [], "k": 0}
                    yield await send_event("topk", {"ts": int(obj.get("ts") or time.time()), "k": int(obj.get("k") or len(obj.get("items") or [])), "items": obj.get("items") or []})
            except Exception as e:
                logger.debug("public: sse message parse fail: %s", e)
                continue
    finally:
        with contextlib.suppress(Exception):
            await pubsub.unsubscribe(PUBSUB_CHANNEL)
            await pubsub.close()

# צריך import קטן
import contextlib

@router.get("/scan/public-stream")
async def public_stream(
    authorization: Optional[str] = Header(None, alias="Authorization"),
    last_event_id: Optional[str] = Header(None, alias="Last-Event-ID"),
):
    if not _bearer_ok(authorization):
        _deny_unauth()
    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",   # ל-Nginx / פרוקסי
    }
    return StreamingResponse(
        _sse_iter(last_event_id),
        media_type="text/event-stream",
        headers=headers,
    )


