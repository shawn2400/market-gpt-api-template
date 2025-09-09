# utils/ws_user_stream.py
from __future__ import annotations
import os, asyncio, json, time, logging
from typing import Optional, Dict, Any

logger = logging.getLogger("algogpt.ws_user")

# ---- Prometheus (אופציונלי) ----
try:
    from prometheus_client import Counter
    _C_WS_EVENTS      = Counter("ws_user_events_total", "Total user-stream WS events")
    _C_WS_ERRORS      = Counter("ws_user_errors_total", "Total user-stream WS errors")
    _C_WS_RECONNECTS  = Counter("ws_user_reconnects_total", "Total user-stream WS reconnects")
    _C_WS_DEDUP_SKIP  = Counter("ws_user_dedup_skips_total", "Deduped review skips")
except Exception:
    class _N:
        def inc(self, *a, **k): pass
    _C_WS_EVENTS=_C_WS_ERRORS=_C_WS_RECONNECTS=_C_WS_DEDUP_SKIP=_N()

# ---- תלות ב-OpenAI review (רשות) ----
try:
    from utils.ai_reviewer import review_trade_async
except Exception:
    async def review_trade_async(*args, **kwargs):
        return {"ok": False, "review": None}

# ---- WS lib (ננסה websockets, ניפול רך אם חסר) ----
try:
    import websockets
except Exception:
    websockets = None

import httpx

BINANCE_FAPI = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com").rstrip("/")
FSTREAM_BASE = os.getenv("BINANCE_FUTURES_WS_BASE", "wss://fstream.binance.com").rstrip("/")
KEEPALIVE_SEC = int(os.getenv("LISTENKEY_KEEPALIVE_SEC", "1800"))
RECONNECT_BACKOFF = float(os.getenv("USER_STREAM_RECONNECT_BACKOFF", "3.0"))
RECONNECT_BACKOFF_MAX = float(os.getenv("USER_STREAM_RECONNECT_MAX_BACKOFF", "60.0"))
ENABLE = os.getenv("USER_STREAM_ENABLE", "1").lower() in ("1","true","yes","on")

API_KEY = os.getenv("BINANCE_API_KEY", "").strip()

_running = False
_task: Optional[asyncio.Task] = None
_listen_key: Optional[str] = None
_last_keepalive = 0.0
_last_event_ts = 0.0
_reconnects = 0
_seen_ids: Dict[str, float] = {}  # idempotency (orderId/execId) -> ts

def is_running() -> bool:
    return _running

def get_stats() -> Dict[str, Any]:
    return {
        "running": _running,
        "listen_key": bool(_listen_key),
        "last_keepalive": _last_keepalive,
        "last_event_ts": _last_event_ts,
        "reconnects": _reconnects,
        "seen_cache": len(_seen_ids),
    }

def start():
    global _running, _task
    if _running: 
        return
    _running = True
    loop = asyncio.get_event_loop()
    _task = loop.create_task(_runner())
    logger.info({"event":"ws_user_stream_started"})

def stop():
    global _running, _task
    _running = False
    if _task and not _task.done():
        _task.cancel()
    logger.info({"event":"ws_user_stream_stopped"})

async def _get_listen_key() -> Optional[str]:
    if not API_KEY:
        logger.warning("BINANCE_API_KEY missing — cannot open user stream")
        return None
    url = f"{BINANCE_FAPI}/fapi/v1/listenKey"
    try:
        async with httpx.AsyncClient(timeout=10.0) as cli:
            r = await cli.post(url, headers={"X-MBX-APIKEY": API_KEY})
            r.raise_for_status()
            return (r.json() or {}).get("listenKey")
    except Exception as e:
        logger.error(f"[ws_user] get listenKey failed: {e}")
        _C_WS_ERRORS.inc()
        return None

async def _keepalive():
    global _last_keepalive
    if not _listen_key or not API_KEY: 
        return
    if time.time() - _last_keepalive < max(KEEPALIVE_SEC - 60, KEEPALIVE_SEC * 0.8):
        return
    url = f"{BINANCE_FAPI}/fapi/v1/listenKey"
    try:
        async with httpx.AsyncClient(timeout=10.0) as cli:
            r = await cli.put(url, headers={"X-MBX-APIKEY": API_KEY}, params={"listenKey": _listen_key})
            if r.is_success:
                _last_keepalive = time.time()
    except Exception as e:
        logger.warning(f"[ws_user] keepalive failed: {e}")
        _C_WS_ERRORS.inc()

def _dedup_key(ev: Dict[str, Any]) -> Optional[str]:
    # ניסיון עדין: נעדיף orderId (i) או execId (t)
    try:
        if ev.get("e") == "ORDER_TRADE_UPDATE":
            o = ev.get("o") or {}
            oi = o.get("i")
            ex = o.get("t")
            return f"o:{oi}" if oi is not None else (f"ex:{ex}" if ex is not None else None)
    except Exception:
        pass
    return None

def _should_review(ev: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    תנאי לטריגר ביקורת:
    - ORDER_TRADE_UPDATE
    - סטטוס סופי: FILLED / CANCELED / EXPIRED
    - לא דופליקט (ע"י _seen_ids)
    """
    if ev.get("e") != "ORDER_TRADE_UPDATE":
        return None
    o = ev.get("o") or {}
    status = (o.get("X") or "").upper()
    if status not in {"FILLED", "CANCELED", "EXPIRED"}:
        return None

    sym = (o.get("s") or "").upper()
    side = (o.get("S") or "").upper()  # BUY/SELL
    # בונים הקשר בסיסי
    ctx = {
        "status": status,
        "order_type": o.get("o"),
        "close_ts": ev.get("T"),
        "exec_type": o.get("x"),
        "avg_price": float(o.get("ap") or 0.0),
        "last_price": float(o.get("L") or 0.0),
        "qty": float(o.get("q") or 0.0),
        "reduce_only": bool(o.get("R") or False),
    }
    side2 = "LONG" if side == "BUY" else ("SHORT" if side == "SELL" else side)
    return {"symbol": sym, "side": side2, "context": ctx}

def _sweep_seen(ttl_sec: float = 900.0):
    now = time.time()
    to_del = [k for k,ts in _seen_ids.items() if now - ts > ttl_sec]
    for k in to_del:
        _seen_ids.pop(k, None)

async def _handle_msg(raw: str):
    global _last_event_ts
    _last_event_ts = time.time()
    _C_WS_EVENTS.inc()
    try:
        ev = json.loads(raw)
    except Exception:
        return
    k = _dedup_key(ev)
    if k:
        if k in _seen_ids:
            _C_WS_DEDUP_SKIP.inc()
            return
        _seen_ids[k] = time.time()
        _sweep_seen()

    review = _should_review(ev)
    if review:
        try:
            await review_trade_async(review["symbol"], review["side"], review["context"], to_telegram=True)
        except Exception as e:
            logger.warning(f"[ws_user] review err: {e}")
            _C_WS_ERRORS.inc()

async def _runner():
    global _listen_key, _reconnects
    if not ENABLE:
        logger.info({"event":"ws_user_stream_disabled"})
        return
    if websockets is None:
        logger.warning("websockets package not available — user stream disabled")
        return

    backoff = RECONNECT_BACKOFF
    while _running:
        try:
            if not _listen_key:
                _listen_key = await _get_listen_key()
                _last_keepalive = time.time()
                if not _listen_key:
                    await asyncio.sleep(backoff)
                    backoff = min(RECONNECT_BACKOFF_MAX, backoff*1.5)
                    continue

            url = f"{FSTREAM_BASE}/ws/{_listen_key}"
            _reconnects += 1
            _C_WS_RECONNECTS.inc()
            logger.info({"event":"ws_user_connect", "url":url})
            async with websockets.connect(url, ping_interval=20, ping_timeout=20, close_timeout=10) as ws:
                backoff = RECONNECT_BACKOFF  # הצליח — אפס backoff
                while _running:
                    await _keepalive()
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=30.0)
                        await _handle_msg(msg)
                    except asyncio.TimeoutError:
                        # אין הודעות — זה תקין. נמשיך לשמור על keepalive
                        continue
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning(f"[ws_user] loop error: {e}")
            _C_WS_ERRORS.inc()
            await asyncio.sleep(backoff)
            backoff = min(RECONNECT_BACKOFF_MAX, backoff*1.5)
    logger.info({"event":"ws_user_runner_exit"})

