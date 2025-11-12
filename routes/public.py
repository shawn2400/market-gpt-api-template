# routes/public.py
from __future__ import annotations
import os, json, time, hashlib, logging, asyncio, contextlib, zlib, hmac, base64
from typing import Any, Dict, List, Optional, AsyncIterator, Tuple
from fastapi import APIRouter, Query, Header, HTTPException, Request, Response, status, Cookie
from fastapi.responses import JSONResponse, StreamingResponse, HTMLResponse, RedirectResponse, PlainTextResponse

logger = logging.getLogger("algogpt.public")
router = APIRouter(tags=["Public Feed"])

# === Env ===
NS = os.getenv("REDIS_NAMESPACE", "ops-supervisor-web").strip() or "ops-supervisor-web"
REDIS_URL = (os.getenv("REDIS_URL") or os.getenv("ALGOGPT_REDIS_URL") or "").strip()

PUBLIC_CACHE_MAX_AGE = int(os.getenv("PUBLIC_CACHE_MAX_AGE", "20") or "20")
PUBLIC_REQUIRE_BEARER = os.getenv("PUBLIC_REQUIRE_BEARER", "0").lower() in ("1","true","yes","on")

API_BEARER_TOKEN = (os.getenv("API_BEARER_TOKEN") or os.getenv("API_TOKEN") or "").strip()

SSE_HEARTBEAT_SEC = int(os.getenv("PUBLIC_SSE_HEARTBEAT_SEC", "20") or "20")
SSE_MAX_IDLE_SEC  = int(os.getenv("PUBLIC_SSE_MAX_IDLE_SEC",  "300") or "300")
SSE_GZIP          = os.getenv("PUBLIC_SSE_GZIP", "0").lower() in ("1","true","yes","on")

# --- Light rate-limit knobs (safe defaults) ---
PUBLIC_WEB_RPS        = int(os.getenv("PUBLIC_WEB_RPS", "2") or "2")
PUBLIC_WEB_BURST      = int(os.getenv("PUBLIC_WEB_BURST", "6") or "6")
PUBLIC_REST_RPS       = int(os.getenv("PUBLIC_REST_RPS", "5") or "5")
PUBLIC_REST_BURST     = int(os.getenv("PUBLIC_REST_BURST", "15") or "15")
PUBLIC_SSE_MAX_CONNS        = int(os.getenv("PUBLIC_SSE_MAX_CONNS", "80") or "80")
PUBLIC_SSE_MAX_CONNS_PER_IP = int(os.getenv("PUBLIC_SSE_MAX_CONNS_PER_IP", "4") or "4")
PUBLIC_RL_NS          = os.getenv("PUBLIC_RL_NS", f"{NS}:rl").strip()

PUBSUB_CHANNEL = f"{NS}:public:events"

# ticket signing secret (fallbacks)
TICKET_SECRET = (
    os.getenv("API_SIGNING_SECRET")
    or os.getenv("OPS_SIGN_SECRET")
    or API_BEARER_TOKEN
).encode("utf-8")
TICKET_DEFAULT_TTL = 600  # 10 דקות
TICKET_MAX_TTL     = 900  # 15 דקות hard cap
TICKET_AUD         = "sse"

# === Optional Token-Bucket (drop-in) ===
_tb_allow = None
try:
    # אם קיים utils/rate_limit_tb.py עם tb_allow (TB_ENABLE=1) — נשתמש בו במקום ה-RL הקל
    from utils.rate_limit_tb import tb_allow as _tb_allow  # type: ignore
except Exception:
    _tb_allow = None

# === Redis (async) ===
_aioredis = None
try:
    import redis.asyncio as _aioredis  # type: ignore
except Exception:
    _aioredis = None

_redis_client = None
_client_lock = asyncio.Lock()

async def _get_redis():
    global _redis_client
    if not (_aioredis and REDIS_URL):
        return None
    if _redis_client:
        return _redis_client
    async with _client_lock:
        if _redis_client:
            return _redis_client
        try:
            _redis_client = _aioredis.from_url(
                REDIS_URL,
                decode_responses=True,
                client_name=os.getenv("REDIS_CLIENT_NAME", "algogpt.public"),
                socket_connect_timeout=float(os.getenv("REDIS_CONNECT_TIMEOUT", "8.0")),
                socket_timeout=float(os.getenv("REDIS_SOCKET_TIMEOUT", "8.0")),
                max_connections=int(os.getenv("REDIS_POOL_MAX_CONNECTIONS", "30")),
            )
        except Exception as e:
            logger.warning("public: redis connect failed: %s", e)
            _redis_client = None
    return _redis_client

# === Small JWT-like (HMAC-SHA256) ticket, no external deps ===
def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

def _b64url_decode(s: str) -> bytes:
    pad = '=' * (-len(s) % 4)
    return base64.urlsafe_b64decode((s + pad).encode("ascii"))

def _sign(parts: List[str]) -> str:
    msg = ".".join(parts).encode("utf-8")
    return _b64url(hmac.new(TICKET_SECRET, msg, hashlib.sha256).digest())

def _issue_ticket(sub: str = "viewer", ttl: int = TICKET_DEFAULT_TTL) -> Tuple[str, int]:
    ttl = int(max(60, min(ttl, TICKET_MAX_TTL)))
    iat = int(time.time())
    exp = iat + ttl
    header = {"alg": "HS256", "typ": "JWT", "aud": TICKET_AUD}
    payload = {"sub": sub, "iat": iat, "exp": exp, "aud": TICKET_AUD}
    p1 = _b64url(json.dumps(header, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    p2 = _b64url(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    sig = _sign([p1, p2])
    return f"{p1}.{p2}.{sig}", exp

def _decode_ticket(token: str) -> Tuple[Optional[dict], Optional[dict]]:
    try:
        p1, p2, _ = token.split(".")
        header = json.loads(_b64url_decode(p1))
        payload = json.loads(_b64url_decode(p2))
        return header, payload
    except Exception:
        return None, None

def _verify_ticket(token: str) -> bool:
    try:
        p1, p2, sig = token.split(".")
    except Exception:
        return False
    good_sig = _sign([p1, p2])
    if not hmac.compare_digest(sig, good_sig):
        return False
    try:
        payload = json.loads(_b64url_decode(p2))
    except Exception:
        return False
    if payload.get("aud") != TICKET_AUD:
        return False
    exp = int(payload.get("exp") or 0)
    if exp < int(time.time()):
        return False
    return True

# === Security helpers ===
def _bearer_header_ok(auth_header: Optional[str]) -> bool:
    if not PUBLIC_REQUIRE_BEARER:
        return True
    if not API_BEARER_TOKEN:
        return False
    if not (auth_header and auth_header.startswith("Bearer ")):
        return False
    return auth_header.split(" ", 1)[1].strip() == API_BEARER_TOKEN

def _extract_any_token(
    request: Request,
    auth_header: Optional[str],
    q_token: Optional[str],
    cookie_auth: Optional[str],
    cookie_sse: Optional[str],
) -> Tuple[str, str]:
    # 1) Authorization: Bearer ...
    if auth_header and auth_header.startswith("Bearer "):
        tok = auth_header.split(" ", 1)[1].strip()
        if API_BEARER_TOKEN and hmac.compare_digest(tok, API_BEARER_TOKEN):
            return "bearer", tok
    # 2) Query t/token
    if q_token:
        tok = q_token.strip()
        if API_BEARER_TOKEN and hmac.compare_digest(tok, API_BEARER_TOKEN):
            return "bearer", tok
        if _verify_ticket(tok):
            return "ticket", tok
    # 3) Cookies
    for tok in (cookie_sse or "", cookie_auth or ""):
        tok = (tok or "").strip()
        if not tok:
            continue
        if API_BEARER_TOKEN and hmac.compare_digest(tok, API_BEARER_TOKEN):
            return "bearer", tok
        if _verify_ticket(tok):
            return "ticket", tok
    return "none", ""

def _deny():
    raise HTTPException(status_code=401, detail="Unauthorized")

# === RL helpers (Redis-based) ===
def _client_ip(request: Request) -> str:
    return (request.client.host if request.client else "0.0.0.0") or "0.0.0.0"

async def _rate_limit(request: Request, scope: str, rps: int, burst: int) -> bool:
    """
    אם קיים Token-Bucket אמיתי (utils.rate_limit_tb + TB_ENABLE=1) — נשתמש בו.
    אחרת: Sliding-second לימיטר קליל (per ip+scope, 1s key).
    """
    ip = _client_ip(request)
    # עדיפות לטוקן־באקט אם קיים
    if _tb_allow is not None:
        try:
            allowed, _ = await _tb_allow(ip, request.url.path, sse_hint=False)
            return bool(allowed)
        except Exception:
            pass

    if rps <= 0 or burst <= 0:
        return True
    r = await _get_redis()
    if not r:
        logger.debug("public: RL skip (no redis)")
        return True
    now = int(time.time())
    key = f"{PUBLIC_RL_NS}:{scope}:{ip}:{now}"
    try:
        n = await r.incr(key)
        if n == 1:
            await r.expire(key, 2)
        limit = max(rps, burst)
        allowed = n <= limit
        if not allowed:
            logger.debug("public: RL hit scope=%s ip=%s n=%s limit=%s", scope, ip, n, limit)
        return allowed
    except Exception as e:
        logger.debug("public: RL error %s", e)
        return True

async def _sse_try_register(request: Request) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Track concurrent SSE connections: global + per-IP. Returns (ok, key_global, key_ip).
    Caller must call _sse_unregister on disconnect.
    """
    r = await _get_redis()
    if not r:
        return True, None, None
    ip = _client_ip(request)
    key_g = f"{PUBLIC_RL_NS}:sse:conn:global"
    key_i = f"{PUBLIC_RL_NS}:sse:conn:ip:{ip}"
    try:
        pipe = r.pipeline()
        pipe.incr(key_g)
        pipe.expire(key_g, 120)
        pipe.incr(key_i)
        pipe.expire(key_i, 120)
        g_val, _, i_val, _ = await pipe.execute()
        if (PUBLIC_SSE_MAX_CONNS > 0 and int(g_val) > PUBLIC_SSE_MAX_CONNS) \
           or (PUBLIC_SSE_MAX_CONNS_PER_IP > 0 and int(i_val) > PUBLIC_SSE_MAX_CONNS_PER_IP):
            with contextlib.suppress(Exception):
                await r.decr(key_g)
                await r.decr(key_i)
            return False, key_g, key_i
        return True, key_g, key_i
    except Exception as e:
        logger.debug("public: sse register error %s", e)
        return True, None, None

async def _sse_touch(keys: Tuple[Optional[str], Optional[str]]) -> None:
    """מרענן TTL כך שמונה חיבורים לא יפוג במהלך חיבור ארוך."""
    r = await _get_redis()
    if not r:
        return
    key_g, key_i = keys
    try:
        pipe = r.pipeline()
        if key_g: pipe.expire(key_g, 120)
        if key_i: pipe.expire(key_i, 120)
        await pipe.execute()
    except Exception:
        pass

async def _sse_unregister(keys: Tuple[Optional[str], Optional[str]]) -> None:
    r = await _get_redis()
    if not r:
        return
    key_g, key_i = keys
    try:
        pipe = r.pipeline()
        if key_g: pipe.decr(key_g)
        if key_i: pipe.decr(key_i)
        await pipe.execute()
    except Exception:
        pass

# === Security headers for HTML/Streams ===
def _secure_html_response(html: str) -> HTMLResponse:
    resp = HTMLResponse(html)
    # חשוב: script-src עם 'unsafe-inline' כי הדפים משתמשים ב-inline JS
    resp.headers.setdefault("Content-Security-Policy",
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "connect-src 'self' https: wss:; "
        "img-src 'self' data:; "
        "object-src 'none'; base-uri 'self'; frame-ancestors 'none'")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    resp.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
    return resp

def _attach_security_headers(resp: Response) -> Response:
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Content-Security-Policy",
        "default-src 'self'; connect-src 'self' https: wss:; object-src 'none'")
    return resp

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

def _symbols_set(symbols: Optional[str]) -> Optional[set]:
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
            if sside in ("BUY", "SELL") and str(it.get("side","")).upper() != sside:
                continue
            if min_score is not None:
                if float(it.get("score", 0.0)) < float(min_score):
                    continue
            out.append(it)
            if len(out) >= k:
                break
        except Exception:
            continue
    return out

def _filter_now(items: List[Dict[str, Any]], symbols_set: Optional[set]) -> List[Dict[str, Any]]:
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

def _json_response(payload: Dict[str, Any], etag: Optional[str], request: Request) -> Response:
    inm = request.headers.get("if-none-match") or request.headers.get("If-None-Match")
    if etag and inm and etag in inm:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED)
    resp = JSONResponse(payload)
    resp.headers.setdefault("Cache-Control", f"public, max-age={PUBLIC_CACHE_MAX_AGE}")
    if etag:
        resp.headers.setdefault("ETag", f"\"{etag}\"")
    return resp

# === REST: NOW ===
@router.get("/scan/public-now")
async def public_now(
    request: Request,
    symbols: Optional[str] = Query(None, description="comma-separated symbols filter, e.g. BTCUSDT,ETHUSDT"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
    t: Optional[str] = Query(None, description="ticket or bearer token"),
    token: Optional[str] = Query(None, description="ticket or bearer token (alias)"),
    auth: Optional[str] = Cookie(None),
    sse_token: Optional[str] = Cookie(None),
):
    if not await _rate_limit(request, "rest_now", PUBLIC_REST_RPS, PUBLIC_REST_BURST):
        raise HTTPException(status_code=429, detail="rate_limited")

    kind, tok = _extract_any_token(request, authorization, t or token, auth, sse_token)
    if PUBLIC_REQUIRE_BEARER and kind == "none":
        _deny()

    obj = await _read_json(f"{NS}:public:now") or {"ts": int(time.time()), "items": []}
    items = obj.get("items") or []
    filt = _filter_now(items, _symbols_set(symbols))
    out = {"ok": True, "ts": int(obj.get("ts") or time.time()), "items": filt}
    etag = _json_md5(out)
    return _json_response(out, etag=etag, request=request)

# === REST: TOPK ===
@router.get("/scan/public-topk")
async def public_topk(
    request: Request,
    k: int = Query(5, ge=1, le=50),
    min_score: Optional[float] = Query(None, ge=0.0),
    side: Optional[str] = Query(None, pattern="(?i)^(buy|sell)$"),
    symbols: Optional[str] = Query(None, description="comma-separated symbols filter"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
    t: Optional[str] = Query(None, description="ticket or bearer token"),
    token: Optional[str] = Query(None, description="ticket or bearer token (alias)"),
    auth: Optional[str] = Cookie(None),
    sse_token: Optional[str] = Cookie(None),
):
    if not await _rate_limit(request, "rest_topk", PUBLIC_REST_RPS, PUBLIC_REST_BURST):
        raise HTTPException(status_code=429, detail="rate_limited")

    kind, tok = _extract_any_token(request, authorization, t or token, auth, sse_token)
    if PUBLIC_REQUIRE_BEARER and kind == "none":
        _deny()

    obj = await _read_json(f"{NS}:public:topk")
    if not obj:
        payload = {"ok": True, "ts": int(time.time()), "k": 0, "items": []}
        return _json_response(payload, etag=_json_md5(payload), request=request)

    items = obj.get("items") or []
    if not isinstance(items, list):
        items = []
    items = _filter_topk(items, k=k, min_score=min_score, side=side, symbols_set=_symbols_set(symbols))
    out = {
        "ok": True,
        "ts": int(obj.get("ts") or time.time()),
        "k": min(k, len(items)),
        "items": items[:k],
    }
    etag = _json_md5(out)
    return _json_response(out, etag=etag, request=request)

@router.get("/scan/public-topk/snapshot")
async def public_topk_snapshot(
    request: Request,
    authorization: Optional[str] = Header(None, alias="Authorization"),
    t: Optional[str] = Query(None),
    token: Optional[str] = Query(None),
    auth: Optional[str] = Cookie(None),
    sse_token: Optional[str] = Cookie(None),
):
    if not await _rate_limit(request, "rest_topk_snap", PUBLIC_REST_RPS, PUBLIC_REST_BURST):
        raise HTTPException(status_code=429, detail="rate_limited")

    kind, tok = _extract_any_token(request, authorization, t or token, auth, sse_token)
    if PUBLIC_REQUIRE_BEARER and kind == "none":
        _deny()

    obj = await _read_json(f"{NS}:public:topk") or {"ts": int(time.time()), "items": []}
    out = {
        "ok": True,
        "ts": int(obj.get("ts") or time.time()),
        "k": int(obj.get("k") or len(obj.get("items") or [])),
        "items": obj.get("items") or []
    }
    return _json_response(out, etag=_json_md5(out), request=request)

# === SSE (Pub/Sub Redis) ===
async def _sse_chunks(last_event_id: Optional[str], accept_gzip: bool, sse_keys: Tuple[Optional[str], Optional[str]]) -> AsyncIterator[bytes]:
    r = await _get_redis()
    started = time.time()
    last_sent = time.time()

    def pack(event: str, data: Dict[str, Any]) -> bytes:
        eid = str(int(data.get("ts") or time.time()))
        body = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        return f"event: {event}\nid: {eid}\ndata: {body}\n\n".encode("utf-8")

    compressor = zlib.compressobj(wbits=16+zlib.MAX_WBITS) if (SSE_GZIP and accept_gzip) else None
    def emit(b: bytes) -> bytes:
        if compressor:
            return compressor.compress(b)
        return b

    # initial snapshots
    try:
        now_obj = await _read_json(f"{NS}:public:now") or {"ts": int(time.time()), "items": []}
        chunk = pack("now", {"ts": int(now_obj.get("ts") or time.time()), "items": now_obj.get("items") or []})
        yield emit(chunk)
        last_sent = time.time()
    except Exception:
        pass
    try:
        topk_obj = await _read_json(f"{NS}:public:topk") or {"ts": int(time.time()), "items": [], "k": 0}
        chunk = pack("topk", {
            "ts": int(topk_obj.get("ts") or time.time()),
            "k": int(topk_obj.get("k") or len(topk_obj.get("items") or [])),
            "items": topk_obj.get("items") or []})
        yield emit(chunk)
        last_sent = time.time()
    except Exception:
        pass

    if not r:
        while True:
            await asyncio.sleep(SSE_HEARTBEAT_SEC)
            if time.time() - last_sent > SSE_MAX_IDLE_SEC:
                break
            yield emit(b": keep-alive\n\n")
        if compressor:
            yield compressor.flush()
        await _sse_unregister(sse_keys)
        return

    pubsub = r.pubsub(ignore_subscribe_messages=True)
    try:
        await pubsub.subscribe(PUBSUB_CHANNEL)
        while True:
            try:
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            except Exception:
                msg = None

            now = time.time()
            # heartbeat + ריענון TTL של מוני SSE
            if now - last_sent >= SSE_HEARTBEAT_SEC:
                await _sse_touch(sse_keys)
                yield emit(b": keep-alive\n\n")
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
                    yield emit(pack("now", {"ts": int(obj.get("ts") or time.time()), "items": obj.get("items") or []}))
                else:
                    obj = await _read_json(f"{NS}:public:topk") or {"ts": int(time.time()), "items": [], "k": 0}
                    yield emit(pack("topk", {
                        "ts": int(obj.get("ts") or time.time()),
                        "k": int(obj.get("k") or len(obj.get("items") or [])),
                        "items": obj.get("items") or []}))
                last_sent = time.time()
            except Exception as e:
                logger.debug("public: sse message parse fail: %s", e)
                continue
    finally:
        with contextlib.suppress(Exception):
            await pubsub.unsubscribe(PUBSUB_CHANNEL)
            await pubsub.close()
        if compressor:
            yield compressor.flush()
        await _sse_unregister(sse_keys)

@router.get("/scan/public-stream")
async def public_stream(
    request: Request,
    authorization: Optional[str] = Header(None, alias="Authorization"),
    last_event_id: Optional[str] = Header(None, alias="Last-Event-ID"),
    t: Optional[str] = Query(None, description="ticket or bearer token"),
    token: Optional[str] = Query(None, description="ticket or bearer token (alias)"),
    auth: Optional[str] = Cookie(None),
    sse_token: Optional[str] = Cookie(None),
):
    # אימות: Bearer או Ticket ב־Query/Cookie
    kind, tok = _extract_any_token(request, authorization, t or token, auth, sse_token)
    if PUBLIC_REQUIRE_BEARER and kind == "none":
        _deny()

    # אופציונלי: TB לשער פתיחת חיבורים
    if _tb_allow is not None:
        ip = _client_ip(request)
        allowed, _ = await _tb_allow(ip, request.url.path, sse_hint=True)
        if not allowed:
            raise HTTPException(status_code=429, detail="rate_limited")

    # Connection caps (global + per-IP)
    ok, key_g, key_i = await _sse_try_register(request)
    if not ok:
        raise HTTPException(status_code=429, detail="too_many_sse_connections")

    accept_gzip = "gzip" in (request.headers.get("accept-encoding","").lower())
    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    if SSE_GZIP and accept_gzip:
        headers["Content-Encoding"] = "gzip"

    resp = StreamingResponse(
        _sse_chunks(last_event_id, accept_gzip=accept_gzip, sse_keys=(key_g, key_i)),
        media_type="text/event-stream",
        headers=headers,
    )
    return _attach_security_headers(resp)

# === Ticket issue (returns JSON and optional Set-Cookie) ===
@router.post("/public/sse-ticket")
@router.get("/public/sse-ticket")
async def issue_sse_ticket(
    request: Request,
    authorization: Optional[str] = Header(None, alias="Authorization"),
    bearer: Optional[str] = Query(None, description="fallback: bearer via query"),
    ttl: Optional[int] = Query(TICKET_DEFAULT_TTL, ge=60, le=TICKET_MAX_TTL),
    cookie: Optional[int] = Query(1, description="1=set cookie, 0=just return JSON"),
):
    ok = False
    if _bearer_header_ok(authorization):
        ok = True
    elif bearer and API_BEARER_TOKEN and hmac.compare_digest(bearer.strip(), API_BEARER_TOKEN):
        ok = True

    if not ok:
        _deny()

    tok, exp = _issue_ticket(sub="viewer", ttl=int(ttl or TICKET_DEFAULT_TTL))
    resp = JSONResponse({"ok": True, "t": tok, "exp": exp})
    if cookie:
        resp.set_cookie(
            key="sse_token",
            value=tok,
            max_age=int((ttl or TICKET_DEFAULT_TTL)),
            httponly=True,
            secure=True,
            samesite="Lax",
            path="/",
        )
    return resp

# === Ticket introspection ===
@router.get("/public/ticket/inspect")
async def ticket_inspect(
    request: Request,
    t: Optional[str] = Query(None, description="ticket (or bearer) to inspect"),
    token: Optional[str] = Query(None, description="alias for t"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
    auth: Optional[str] = Cookie(None),
    sse_token: Optional[str] = Cookie(None),
):
    q = (t or token or "").strip()
    if q and API_BEARER_TOKEN and hmac.compare_digest(q, API_BEARER_TOKEN):
        return JSONResponse({"valid": True, "kind": "bearer", "info": {"note": "bearer matches API_BEARER_TOKEN"}})

    if not q:
        if authorization and authorization.startswith("Bearer "):
            val = authorization.split(" ", 1)[1].strip()
            if API_BEARER_TOKEN and hmac.compare_digest(val, API_BEARER_TOKEN):
                return JSONResponse({"valid": True, "kind": "bearer", "info": {"note": "bearer matches API_BEARER_TOKEN"}})
        for cand in (sse_token or "", auth or ""):
            cand = cand.strip()
            if not cand:
                continue
            if API_BEARER_TOKEN and hmac.compare_digest(cand, API_BEARER_TOKEN):
                return JSONResponse({"valid": True, "kind": "bearer", "info": {"note": "bearer matches API_BEARER_TOKEN"}})
            q = cand
            break

    if not q:
        return JSONResponse({"valid": False, "error": "no token provided"}, status_code=400)

    valid = _verify_ticket(q)
    h, p = _decode_ticket(q)
    return JSONResponse({
        "valid": bool(valid),
        "kind": "ticket",
        "header": h or {},
        "payload": p or {},
        "now": int(time.time()),
    }, status_code=200 if valid else 400)

# === Legacy redirect: /topk -> /scan/public-topk ===
@router.get("/topk")
async def legacy_topk_redirect(request: Request):
    dest = "/scan/public-topk"
    if request.url.query:
        dest = f"{dest}?{request.url.query}"
    return RedirectResponse(url=dest, status_code=status.HTTP_307_TEMPORARY_REDIRECT)

# === CSV export: /topk.csv ===
@router.get("/topk.csv")
async def topk_csv(
    request: Request,
    k: int = Query(5, ge=1, le=200),
    min_score: Optional[float] = Query(None, ge=0.0),
    side: Optional[str] = Query(None, pattern="(?i)^(buy|sell)$"),
    symbols: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None, alias="Authorization"),
    t: Optional[str] = Query(None),
    token: Optional[str] = Query(None),
    auth: Optional[str] = Cookie(None),
    sse_token: Optional[str] = Cookie(None),
):
    if not await _rate_limit(request, "rest_topk_csv", PUBLIC_REST_RPS, PUBLIC_REST_BURST):
        raise HTTPException(status_code=429, detail="rate_limited")

    kind, tok = _extract_any_token(request, authorization, t or token, auth, sse_token)
    if PUBLIC_REQUIRE_BEARER and kind == "none":
        _deny()

    obj = await _read_json(f"{NS}:public:topk") or {"ts": int(time.time()), "items": []}
    items = obj.get("items") or []
    items = _filter_topk(items, k=k, min_score=min_score, side=side, symbols_set=_symbols_set(symbols))

    cols = ["symbol","side","score","timeframe","entry_price","tp1","tp2","tp3","sl","reason","prob_overall_pct","prob_tp1_pct","prob_tp2_pct","prob_tp3_pct","eta_open_min","eta_tp1_min","eta_tp2_min","eta_tp3_min","ts"]
    lines = [",".join(cols)]
    for it in items:
        row = []
        for c in cols:
            v = it.get(c, "")
            if isinstance(v, (list, dict)):
                v = json.dumps(v, ensure_ascii=False, separators=(",", ":"))
            s = str(v).replace("\n", " ").replace("\r", " ").replace(",", " ")
            row.append(s)
        lines.append(",".join(row))
    payload = "\n".join(lines) + "\n"

    resp = PlainTextResponse(
        payload,
        media_type="text/csv; charset=utf-8",
        headers={
            "Cache-Control": f"public, max-age={PUBLIC_CACHE_MAX_AGE}",
            "Content-Disposition": 'inline; filename="topk.csv"',
        },
    )
    return _attach_security_headers(resp)

# === Lightweight HTML web (SSE-first, polling fallback) for TOPK ===
@router.get("/scan/public-topk/web")
async def public_topk_web(request: Request) -> HTMLResponse:
    if not await _rate_limit(request, "web_topk", PUBLIC_WEB_RPS, PUBLIC_WEB_BURST):
        return _secure_html_response("<!doctype html><title>Too Many Requests</title><h3 style='font-family:sans-serif;color:#e11d48'>Rate limited</h3>")
    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>AlgoGPT — Live TopK</title>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<style>
  body {{ font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif; margin: 0; background: #0b0f14; color: #e2e8f0; }}
  header {{ position: sticky; top:0; background: #0b0f14; padding: 12px 16px; border-bottom: 1px solid #1f2937; display:flex; gap:12px; align-items:center; }}
  .badge {{ font-size:12px; padding:2px 8px; border-radius:999px; background:#1f2937; }}
  .ok {{ background:#065f46; }}
  .err {{ background:#7f1d1d; }}
  table {{ width: 100%; border-collapse: collapse; }}
  th, td {{ padding: 8px 10px; border-bottom: 1px solid #1f2937; font-size:14px; }}
  th {{ text-align:left; color:#94a3b8; }}
  .buy {{ color:#10b981; font-weight:600; }}
  .sell {{ color:#ef4444; font-weight:600; }}
  .muted {{ color:#94a3b8; }}
  .row:hover {{ background:#0f172a; }}
  .wrap {{ max-width: 1100px; margin: 0 auto; padding: 0 12px; }}
</style>
</head>
<body>
<header class="wrap">
  <div><strong>TopK Live</strong> <span id="status" class="badge">connecting…</span></div>
  <div class="muted" id="stamp"></div>
</header>
<div class="wrap">
  <table>
    <thead>
      <tr>
        <th>Symbol</th><th>Side</th><th>Score</th><th>TF</th><th>Entry</th><th>TPs</th><th>SL</th><th>Why</th>
      </tr>
    </thead>
    <tbody id="rows"></tbody>
  </table>
</div>
<script>
(function() {{
  const qs = new URLSearchParams(location.search);
  const t = qs.get('t') || qs.get('token') || '';
  const rows = document.getElementById('rows');
  const status = document.getElementById('status');
  const stamp  = document.getElementById('stamp');

  function fmt(n, d=2) {{ 
    if (n === undefined || n === null || isNaN(n)) return '';
    return Number(n).toFixed(d);
  }}
  function paintTopk(items) {{
    rows.innerHTML = '';
    for (const it of items) {{
      const tr = document.createElement('tr');
      tr.className = 'row';
      const side = (it.side||'').toUpperCase();
      const tp1 = it.tp1 ?? '';
      const tp2 = it.tp2 ?? '';
      const tp3 = it.tp3 ?? '';
      tr.innerHTML = `
        <td><strong>${{it.symbol||''}}</strong></td>
        <td class="${{side==='BUY'?'buy':'sell'}}">${{side}}</td>
        <td>${{fmt(it.score||0,2)}}</td>
        <td class="muted">${{it.timeframe||''}}</td>
        <td>${{fmt(it.entry_price||it.price||'', 4)}}</td>
        <td class="muted">${{[tp1,tp2,tp3].filter(x=>x!==''&&x!==undefined).join(' / ')}}</td>
        <td class="muted">${{it.sl??''}}</td>
        <td class="muted">${{(it.reason||'').slice(0,80)}}</td>
      `;
      rows.appendChild(tr);
    }}
    stamp.textContent = new Date().toLocaleTimeString();
  }}

  let es;
  function startSSE() {{
    status.textContent = 'connecting…';
    try {{
      const url = new URL('/scan/public-stream', location.origin);
      const qs = new URLSearchParams(location.search);
      const t = qs.get('t') || qs.get('token') || '';
      if (t) url.searchParams.set('t', t);
      es = new EventSource(url.toString());
      es.addEventListener('topk', (e)=>{{
        try {{
          const data = JSON.parse(e.data||'{{}}');
          paintTopk(data.items||[]);
          status.textContent = 'live';
          status.className = 'badge ok';
        }} catch {{}}
      }});
      es.addEventListener('open', ()=> {{
        status.textContent = 'live';
        status.className = 'badge ok';
      }});
      es.addEventListener('error', ()=> {{
        status.textContent = 'disconnected';
        status.className = 'badge err';
        es && es.close();
        setTimeout(()=> startPolling(), 1200);
      }});
    }} catch (e) {{
      startPolling();
    }}
  }}

  let poller;
  async function startPolling() {{
    if (poller) clearInterval(poller);
    async function pull() {{
      try {{
        const url = new URL('/scan/public-topk', location.origin);
        const qs = new URLSearchParams(location.search);
        const t = qs.get('t') || qs.get('token') || '';
        if (t) url.searchParams.set('t', t);
        url.searchParams.set('k', '10');
        const res = await fetch(url.toString(), {{ credentials: 'same-origin' }});
        if (!res.ok) throw new Error('http '+res.status);
        const data = await res.json();
        paintTopk(data.items||[]);
        status.textContent = 'polling';
        status.className = 'badge';
      }} catch (e) {{
        status.textContent = 'error';
        status.className = 'badge err';
      }}
    }}
    await pull();
    poller = setInterval(pull, 10000);
  }}

  startSSE();
}})();
</script>
</body>
</html>"""
    return _secure_html_response(html)

# === Lightweight HTML web (SSE-first, polling fallback) for NOW ===
@router.get("/scan/public-now/web")
async def public_now_web(request: Request) -> HTMLResponse:
    if not await _rate_limit(request, "web_now", PUBLIC_WEB_RPS, PUBLIC_WEB_BURST):
        return _secure_html_response("<!doctype html><title>Too Many Requests</title><h3 style='font-family:sans-serif;color:#e11d48'>Rate limited</h3>")
    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>AlgoGPT — Live Now</title>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<style>
  body {{ font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif; margin: 0; background: #0b0f14; color: #e2e8f0; }}
  header {{ position: sticky; top:0; background: #0b0f14; padding: 12px 16px; border-bottom: 1px solid #1f2937; display:flex; gap:12px; align-items:center; flex-wrap:wrap; }}
  .badge {{ font-size:12px; padding:2px 8px; border-radius:999px; background:#1f2937; }}
  .ok {{ background:#065f46; }}
  .err {{ background:#7f1d1d; }}
  table {{ width: 100%; border-collapse: collapse; }}
  th, td {{ padding: 8px 10px; border-bottom: 1px solid #1f2937; font-size:14px; }}
  th {{ text-align:left; color:#94a3b8; }}
  .buy {{ color:#10b981; font-weight:600; }}
  .sell {{ color:#ef4444; font-weight:600; }}
  .muted {{ color:#94a3b8; }}
  .row:hover {{ background:#0f172a; }}
  .wrap {{ max-width: 1200px; margin: 0 auto; padding: 0 12px; }}
  input, select {{ background:#0f172a; color:#e5e7eb; border:1px solid #1f2937; border-radius:8px; padding:6px 8px; }}
</style>
</head>
<body>
<header class="wrap">
  <div><strong>Now Live</strong> <span id="status" class="badge">connecting…</span></div>
  <div class="muted" id="stamp"></div>
</header>
<div class="wrap">
  <table>
    <thead>
      <tr>
        <th>Symbol</th><th>Side</th><th>Score</th><th>TF</th><th>Price</th><th>Entry</th><th>TPs</th><th>SL</th><th>Why</th>
      </tr>
    </thead>
    <tbody id="rows"></tbody>
  </table>
</div>
<script>
(function() {{
  const qs = new URLSearchParams(location.search);
  const t = qs.get('t') || qs.get('token') || '';
  const rows = document.getElementById('rows');
  const status = document.getElementById('status');
  const stamp  = document.getElementById('stamp');

  function fmt(n, d=4) {{
    if (n === undefined || n === null || isNaN(n)) return '';
    return Number(n).toFixed(d);
  }}
  function paintNow(items) {{
    rows.innerHTML = '';
    for (const it of items) {{
      const tr = document.createElement('tr');
      tr.className = 'row';
      const side = (it.side||'').toUpperCase();
      const tp1 = it.tp1 ?? '';
      const tp2 = it.tp2 ?? '';
      const tp3 = it.tp3 ?? '';
      tr.innerHTML = `
        <td><strong>${{it.symbol||''}}</strong></td>
        <td class="${{side==='BUY'?'buy':'sell'}}">${{side}}</td>
        <td>${{(it.score!==undefined && it.score!==null) ? Number(it.score).toFixed(2) : ''}}</td>
        <td class="muted">${{it.timeframe||''}}</td>
        <td>${{fmt(it.price||'', 4)}}</td>
        <td>${{fmt(it.entry_price||'', 4)}}</td>
        <td class="muted">${{[tp1,tp2,tp3].filter(x=>x!==''&&x!==undefined).join(' / ')}}</td>
        <td class="muted">${{it.sl??''}}</td>
        <td class="muted">${{(it.reason||'').slice(0,80)}}</td>
      `;
      rows.appendChild(tr);
    }}
    stamp.textContent = new Date().toLocaleTimeString();
  }}

  let es;
  function startSSE() {{
    status.textContent = 'connecting…';
    try {{
      const url = new URL('/scan/public-stream', location.origin);
      if (t) url.searchParams.set('t', t);
      es = new EventSource(url.toString());
      es.addEventListener('now', (e)=>{{
        try {{
          const data = JSON.parse(e.data||'{{}}');
          paintNow((data.items||[]));
          status.textContent = 'live';
          status.className = 'badge ok';
        }} catch {{}}
      }});
      es.addEventListener('open', ()=> {{
        status.textContent = 'live';
        status.className = 'badge ok';
      }});
      es.addEventListener('error', ()=> {{
        status.textContent = 'disconnected';
        status.className = 'badge err';
        es && es.close();
        setTimeout(()=> startPolling(), 1200);
      }});
    }} catch (e) {{
      startPolling();
    }}
  }}

  let poller;
  async function startPolling() {{
    if (poller) clearInterval(poller);
    async function pull() {{
      try {{
        const url = new URL('/scan/public-now', location.origin);
        if (t) url.searchParams.set('t', t);
        const res = await fetch(url.toString(), {{ credentials: 'same-origin' }});
        if (!res.ok) throw new Error('http '+res.status);
        const data = await res.json();
        paintNow(data.items||[]);
        status.textContent = 'polling';
        status.className = 'badge';
      }} catch (e) {{
        status.textContent = 'error';
        status.className = 'badge err';
      }}
    }}
    await pull();
    poller = setInterval(pull, 10000);
  }}

  startSSE();
}})();
</script>
</body>
</html>"""
    return _secure_html_response(html)




