# routes/public.py
from __future__ import annotations
import os, json, time, hashlib, logging, asyncio, contextlib, zlib, io, csv
from typing import Any, Dict, List, Optional, AsyncIterator, Set

from fastapi import APIRouter, Query, Header, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse, StreamingResponse, RedirectResponse, HTMLResponse

logger = logging.getLogger("algogpt.public")
router = APIRouter(tags=["Public Feed"])

# === Env ===
NS = os.getenv("REDIS_NAMESPACE", "ops-supervisor-web").strip() or "ops-supervisor-web"
REDIS_URL = (os.getenv("REDIS_URL") or os.getenv("ALGOGPT_REDIS_URL") or "").strip()
PUBLIC_CACHE_MAX_AGE = int(os.getenv("PUBLIC_CACHE_MAX_AGE", "20") or "20")
PUBLIC_REQUIRE_BEARER = os.getenv("PUBLIC_REQUIRE_BEARER", "1").lower() in ("1","true","yes","on")
API_BEARER_TOKEN = (os.getenv("API_BEARER_TOKEN") or os.getenv("API_TOKEN") or "").strip()
SSE_HEARTBEAT_SEC = int(os.getenv("PUBLIC_SSE_HEARTBEAT_SEC", "20") or "20")
SSE_MAX_IDLE_SEC = int(os.getenv("PUBLIC_SSE_MAX_IDLE_SEC", "300") or "300")
PUBSUB_CHANNEL = f"{NS}:public:events"
SSE_GZIP = os.getenv("PUBLIC_SSE_GZIP", "0").lower() in ("1","true","yes","on")

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
            _redis_client = _aioredis.from_url(REDIS_URL, decode_responses=True)
        except Exception as e:
            logger.warning("public: redis connect failed: %s", e)
            _redis_client = None
    return _redis_client

# === Security ===
def _bearer_ok(auth_header: Optional[str]) -> bool:
    if not PUBLIC_REQUIRE_BEARER:
        return True
    if not API_BEARER_TOKEN:
        return False
    if not (auth_header and auth_header.startswith("Bearer ")):
        return False
    return auth_header.split(" ", 1)[1].strip() == API_BEARER_TOKEN

def _deny():
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

def _symbols_set(symbols: Optional[str]) -> Optional[Set[str]]:
    if not symbols:
        return None
    s = [x.strip().upper() for x in symbols.split(",") if x.strip()]
    return set(s) if s else None

def _filter_topk(items: List[Dict[str, Any]],
                 k: int,
                 min_score: Optional[float],
                 side: Optional[str],
                 symbols_set: Optional[Set[str]]) -> List[Dict[str, Any]]:
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

def _filter_now(items: List[Dict[str, Any]], symbols_set: Optional[Set[str]]) -> List[Dict[str, Any]]:
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
    # If-None-Match -> 304
    inm = request.headers.get("if-none-match") or request.headers.get("If-None-Match")
    if etag and inm and etag in inm:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED)
    resp = JSONResponse(payload)
    resp.headers.setdefault("Cache-Control", f"public, max-age={PUBLIC_CACHE_MAX_AGE}")
    if etag:
        resp.headers.setdefault("ETag", f"\"{etag}\"")
    return resp

# === LEGACY REDIRECTS / PROXY ===

@router.get("/topk")
async def legacy_topk_redirect(request: Request):
    """
    תאימות לאחור: מפנה לנתיב החדש, משמר querystring ומתודה.
    """
    target = str(request.url.replace(path="/scan/public-topk"))
    return RedirectResponse(url=target, status_code=status.HTTP_307_TEMPORARY_REDIRECT)

@router.get("/now")
async def legacy_now_redirect(request: Request):
    target = str(request.url.replace(path="/scan/public-now"))
    return RedirectResponse(url=target, status_code=status.HTTP_307_TEMPORARY_REDIRECT)

@router.get("/topk.json")
async def legacy_topk_proxy(
    request: Request,
    k: int = Query(5, ge=1, le=50),
    min_score: Optional[float] = Query(None, ge=0.0),
    side: Optional[str] = Query(None, pattern="^(?i)(buy|sell)$"),
    symbols: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    """
    תאימות לאחור ללא רידיירקט: מחזיר JSON זהה ל-/scan/public-topk
    ושומר Authorization (אין איבוד כותרות).
    """
    return await public_topk(
        request=request,
        k=k,
        min_score=min_score,
        side=side,
        symbols=symbols,
        authorization=authorization,
    )

# === REST ===

@router.get("/scan/public-now")
async def public_now(
    request: Request,
    symbols: Optional[str] = Query(None, description="comma-separated symbols filter, e.g. BTCUSDT,ETHUSDT"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    if not _bearer_ok(authorization):
        _deny()
    obj = await _read_json(f"{NS}:public:now") or {"ts": int(time.time()), "items": []}
    items = obj.get("items") or []
    filt = _filter_now(items, _symbols_set(symbols))
    out = {"ok": True, "ts": int(obj.get("ts") or time.time()), "items": filt}
    etag = _json_md5(out)
    return _json_response(out, etag=etag, request=request)

@router.get("/scan/public-topk")
async def public_topk(
    request: Request,
    k: int = Query(5, ge=1, le=50),
    min_score: Optional[float] = Query(None, ge=0.0),
    side: Optional[str] = Query(None, pattern="^(?i)(buy|sell)$"),
    symbols: Optional[str] = Query(None, description="comma-separated symbols filter"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    if not _bearer_ok(authorization):
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
):
    if not _bearer_ok(authorization):
        _deny()
    obj = await _read_json(f"{NS}:public:topk") or {"ts": int(time.time()), "items": []}
    out = {
        "ok": True,
        "ts": int(obj.get("ts") or time.time()),
        "k": int(obj.get("k") or len(obj.get("items") or [])),
        "items": obj.get("items") or []
    }
    return _json_response(out, etag=_json_md5(out), request=request)

# === CSV Export ===

@router.get("/topk.csv")
async def public_topk_csv(
    request: Request,
    k: int = Query(5, ge=1, le=50),
    min_score: Optional[float] = Query(None, ge=0.0),
    side: Optional[str] = Query(None, pattern="^(?i)(buy|sell)$"),
    symbols: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    """
    ייצוא CSV ל-topk עם אותם פילטרים/סינונים.
    """
    if not _bearer_ok(authorization):
        _deny()

    obj = await _read_json(f"{NS}:public:topk") or {"ts": int(time.time()), "items": []}
    items = obj.get("items") or []
    items = _filter_topk(items, k=k, min_score=min_score, side=side, symbols_set=_symbols_set(symbols))

    # הכנת CSV קטן בזיכרון (k<=50 — זניח)
    buf = io.StringIO()
    writer = csv.writer(buf)
    # כותרת: תעדוף שדות שכיחים; כותבים רק אם קיימים באייטם הראשון
    header = ["symbol","side","score","price","timeframe","reason","tp1","tp2","tp3","sl","prob_overall_pct"]
    writer.writerow(header)
    for it in items:
        row = [
            it.get("symbol"),
            it.get("side"),
            it.get("score"),
            it.get("price") or it.get("entry_price"),
            it.get("timeframe"),
            (it.get("reason") or "").replace("\n"," ").strip(),
            it.get("tp1"),
            it.get("tp2"),
            it.get("tp3"),
            it.get("sl"),
            it.get("prob_overall_pct"),
        ]
        writer.writerow(row)

    data = buf.getvalue().encode("utf-8")
    etag = hashlib.md5(data).hexdigest()
    headers = {
        "Content-Type": "text/csv; charset=utf-8",
        "Content-Disposition": 'attachment; filename="topk.csv"',
        "Cache-Control": f"public, max-age={PUBLIC_CACHE_MAX_AGE}",
        "ETag": f"\"{etag}\"",
    }

    # If-None-Match -> 304
    inm = request.headers.get("if-none-match") or request.headers.get("If-None-Match")
    if etag and inm and etag in inm:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED)

    return Response(content=data, media_type="text/csv; charset=utf-8", headers=headers)

# === SSE (Pub/Sub Redis) ===
async def _sse_chunks(last_event_id: Optional[str], accept_gzip: bool) -> AsyncIterator[bytes]:
    r = await _get_redis()
    started = time.time()
    last_sent = time.time()

    def pack(event: str, data: Dict[str, Any]) -> bytes:
        eid = str(int(data.get("ts") or time.time()))
        body = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        return f"event: {event}\nid: {eid}\ndata: {body}\n\n".encode("utf-8")

    # optional gzip (ברירת מחדל OFF כי פרוקסים לעתים עושים באפרינג)
    compressor = zlib.compressobj(wbits=16+zlib.MAX_WBITS) if (SSE_GZIP and accept_gzip) else None
    def emit(b: bytes) -> bytes:
        if compressor:
            return compressor.compress(b)
        return b

    # first snapshots
    try:
        now_obj = await _read_json(f"{NS}:public:now") or {"ts": int(time.time()), "items": []}
        chunk = pack("now", {"ts": int(now_obj.get("ts") or time.time()), "items": now_obj.get("items") or []})
        yield emit(chunk)
        last_sent = time.time()
    except Exception:
        pass
    try:
        topk_obj = await _read_json(f"{NS}:public:topk") or {"ts": int(time.time()), "items": [], "k": 0}
        chunk = pack("topk", {"ts": int(topk_obj.get("ts") or time.time()), "k": int(topk_obj.get("k") or len(topk_obj.get("items") or [])), "items": topk_obj.get("items") or []})
        yield emit(chunk)
        last_sent = time.time()
    except Exception:
        pass

    if not r:
        # אין Redis — שולחים heartbeat בלבד עד ניתוק עדין
        while True:
            await asyncio.sleep(SSE_HEARTBEAT_SEC)
            if time.time() - last_sent > SSE_MAX_IDLE_SEC:
                break
            yield emit(b": keep-alive\n\n")
        if compressor:
            yield compressor.flush()
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
            if now - last_sent >= SSE_HEARTBEAT_SEC:
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
                    yield emit(pack("topk", {"ts": int(obj.get("ts") or time.time()), "k": int(obj.get("k") or len(obj.get("items") or [])), "items": obj.get("items") or []}))
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

@router.get("/scan/public-stream")
async def public_stream(
    request: Request,
    authorization: Optional[str] = Header(None, alias="Authorization"),
    last_event_id: Optional[str] = Header(None, alias="Last-Event-ID"),
):
    if not _bearer_ok(authorization):
        _deny()
    accept_gzip = "gzip" in (request.headers.get("accept-encoding","").lower())
    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    if SSE_GZIP and accept_gzip:
        headers["Content-Encoding"] = "gzip"
    return StreamingResponse(
        _sse_chunks(last_event_id, accept_gzip=accept_gzip),
        media_type="text/event-stream",
        headers=headers,
    )

# === Lightweight HTML monitor ===

@router.get("/scan/public-topk/web")
async def public_topk_web() -> HTMLResponse:
    """
    דף HTML קל־משקל לצפייה חיה ב-topk/now.
    עובד עם polling + Authorization Header שהמשתמש מדביק ידנית (נמנע משינוי backend).
    """
    html = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta http-equiv="Cache-Control" content="no-store" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>AlgoGPT — Public TopK Live</title>
<style>
  :root { color-scheme: dark light; }
  body { font: 14px/1.4 system-ui, -apple-system, Segoe UI, Roboto, "Helvetica Neue", Arial, Noto Sans, "Apple Color Emoji","Segoe UI Emoji"; margin: 16px; }
  header { display:flex; gap:12px; align-items:center; flex-wrap:wrap; }
  input[type="text"]{ padding:6px 8px; min-width:280px; }
  .row { display:grid; grid-template-columns: 110px 60px 60px 100px 1fr; gap:8px; padding:8px; border-bottom: 1px solid #4444; }
  .head { font-weight:600; border-bottom: 2px solid #8884; }
  .buy { color: #0a0; font-weight:600; }
  .sell { color: #d33; font-weight:600; }
  .muted { opacity:.7 }
  .wrap { max-width: 1100px; }
  .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace; }
</style>
</head>
<body>
  <header>
    <h2>TopK Live</h2>
    <label>Bearer: <input id="token" type="text" placeholder="paste API Bearer token" /></label>
    <label>Symbols: <input id="symbols" type="text" placeholder="BTCUSDT,ETHUSDT" /></label>
    <label>Side: 
      <select id="side">
        <option value="">Any</option>
        <option value="BUY">BUY</option>
        <option value="SELL">SELL</option>
      </select>
    </label>
    <label>Min score: <input id="min_score" type="number" step="0.1" min="0" style="width:80px"/></label>
    <label>K: <input id="k" type="number" min="1" max="50" value="10" style="width:60px"/></label>
    <button id="go">Refresh</button>
    <span class="muted mono" id="ts"></span>
  </header>

  <div class="wrap">
    <div class="row head"><div>Symbol</div><div>Side</div><div>Score</div><div>Price</div><div>Why</div></div>
    <div id="list"></div>
  </div>

<script>
const $ = (s)=>document.querySelector(s);
function fmtTs(t){ const d = new Date((t||0)*1000); return isFinite(+d)? d.toISOString().replace('T',' ').replace('Z',' UTC'):''; }

async function fetchTopk(){
  const tok = $("#token").value.trim();
  const k = +($("#k").value||10);
  const params = new URLSearchParams();
  params.set("k", String(Math.max(1, Math.min(50, k))));
  const ms = $("#min_score").value.trim(); if (ms) params.set("min_score", ms);
  const sd = $("#side").value; if (sd) params.set("side", sd);
  const sy = $("#symbols").value.trim(); if (sy) params.set("symbols", sy);

  const headers = {};
  if (tok) headers["Authorization"] = "Bearer " + tok;

  const res = await fetch("/scan/public-topk?"+params.toString(), { headers });
  if (!res.ok) throw new Error("HTTP " + res.status);
  const data = await res.json();
  $("#ts").textContent = "ts: " + fmtTs(data.ts) + " | k=" + data.k;
  const list = $("#list");
  list.innerHTML = "";
  (data.items||[]).forEach(x=>{
    const row = document.createElement("div");
    row.className = "row";
    const side = String(x.side||"").toUpperCase();
    row.innerHTML = `
      <div>${x.symbol||""}</div>
      <div class="${side==="BUY"?"buy":(side==="SELL"?"sell":"")}">${side||""}</div>
      <div>${(x.score??"").toString()}</div>
      <div>${(x.price??x.entry_price??"")}</div>
      <div>${(x.reason||"").replace(/\\n/g," ")}</div>`;
    list.appendChild(row);
  });
}

$("#go").addEventListener("click", fetchTopk);
setInterval(()=>{ $("#go").disabled = true; fetchTopk().finally(()=>$("#go").disabled=false); }, 15000);
fetchTopk().catch(console.error);
</script>
</body>
</html>
"""
    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})


