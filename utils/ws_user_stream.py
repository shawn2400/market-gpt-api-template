# utils/ws_user_stream.py
from __future__ import annotations
import os, asyncio, json, time, logging, random
from typing import Optional, Any, Dict

logger = logging.getLogger("algogpt.ws_user")

try:
    import websockets  # type: ignore
except Exception:
    websockets = None

import httpx
from prometheus_client import Counter, Gauge

# runtime counters hooks
try:
    from utils.runtime_counters import ws_note_event, ws_note_reconnect, ws_note_up
except Exception:
    def ws_note_event(*a, **k): pass
    def ws_note_reconnect(*a, **k): pass
    def ws_note_up(*a, **k): pass

WS_EVENTS_TOTAL = Counter("ws_user_events_total", "User-Stream events", ["type"])
WS_ERRORS_TOTAL = Counter("ws_user_errors_total", "User-Stream errors", ["stage"])
WS_UP = Gauge("ws_user_up", "Is WS user stream up (1/0)")

_BINANCE_FAPI = os.getenv("BINANCE_FUTURES_WS_BASE", "wss://fstream.binance.com").rstrip("/")
_BINANCE_HTTP = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com").rstrip("/")

LISTENKEY_KEEPALIVE_SEC = int(os.getenv("LISTENKEY_KEEPALIVE_SEC", "1800"))
LOG_SAMPLE_N            = int(os.getenv("WS_LOG_SAMPLE_N", "20"))

_running = False
_task: Optional[asyncio.Task] = None
_listen_key: Optional[str] = None
_sample_ix = 0
_seen_event: Dict[str,bool] = {}
_seen_cap = 4096

def _sample_ok() -> bool:
    global _sample_ix
    _sample_ix += 1
    return (_sample_ix % max(1, LOG_SAMPLE_N)) == 0

def status() -> Dict[str, Any]:
    return {
        "running": bool(_running),
        "have_listen_key": bool(_listen_key),
        "ws_up": int(WS_UP._value.get() if hasattr(WS_UP, "_value") else 0),
    }

async def _get_listen_key() -> Optional[str]:
    api_key = os.getenv("BINANCE_API_KEY","").strip()
    if not api_key:
        logger.warning({"event":"ws.no_api_key"})
        return None
    url = f"{_BINANCE_HTTP}/fapi/v1/listenKey"
    try:
        async with httpx.AsyncClient(timeout=10.0) as cli:
            r = await cli.post(url, headers={"X-MBX-APIKEY": api_key})
            r.raise_for_status()
            return r.json().get("listenKey")
    except Exception as e:
        WS_ERRORS_TOTAL.labels("get_listen_key").inc()
        logger.warning({"event":"ws.get_listen_key_failed", "error": str(e)})
        return None

async def _keepalive_loop():
    global _listen_key
    while _running and _listen_key:
        await asyncio.sleep(max(60, LISTENKEY_KEEPALIVE_SEC - 60))
        try:
            url = f"{_BINANCE_HTTP}/fapi/v1/listenKey"
            api_key = os.getenv("BINANCE_API_KEY","").strip()
            async with httpx.AsyncClient(timeout=10.0) as cli:
                r = await cli.put(url, headers={"X-MBX-APIKEY": api_key})
                r.raise_for_status()
            if _sample_ok():
                logger.debug({"event":"ws.keepalive_ok"})
        except Exception as e:
            WS_ERRORS_TOTAL.labels("keepalive").inc()
            logger.warning({"event":"ws.keepalive_failed", "error": str(e)})

def _jitter(base: float, pct: float = 0.1) -> float:
    delta = base * pct
    return base + random.uniform(-delta, delta)

async def _handle_event(msg: Dict[str, Any]):
    etype = (msg.get("e") or msg.get("eventType") or "").upper() or "UNKNOWN"
    WS_EVENTS_TOTAL.labels(etype).inc()

    # latency from event-time (E) to now
    lat_ms = None
    try:
        if "E" in msg:
            lat_ms = max(0.0, (time.time() * 1000.0) - float(msg.get("E", 0)))
    except Exception:
        lat_ms = None
    ws_note_event(latency_ms=lat_ms)

    if _sample_ok():
        logger.debug({"event":"ws.recv", "etype": etype, "lat_ms": lat_ms})

    if etype in ("ORDER_TRADE_UPDATE","ORDER_UPDATE","ACCOUNT_UPDATE"):
        uniq = str(msg.get("E") or msg.get("T") or msg.get("t") or json.dumps(msg, sort_keys=True)[:64])
        if uniq in _seen_event: return
        _seen_event[uniq] = True
        if len(_seen_event) > _seen_cap: _seen_event.clear()

        # Hook ביקורת AI על סגירה
        try:
            if etype in ("ORDER_TRADE_UPDATE","ORDER_UPDATE"):
                o = msg.get("o") or msg.get("order") or {}
                status = (o.get("X") or o.get("orderStatus") or "").upper()
                if status in ("FILLED","CANCELED","EXPIRED"):
                    if os.getenv("AI_REVIEW_ENABLE","1").lower() in ("1","true","yes","on"):
                        try:
                            from utils.ai_reviewer import review_trade_async
                            sym = (o.get("s") or o.get("symbol") or "").upper()
                            sd  = "LONG" if (o.get("S") or o.get("side") or "").upper() == "BUY" else "SHORT"
                            ctx = {"status": status, "filled": o.get("z") or o.get("filledQty"),
                                   "avgPrice": o.get("ap") or o.get("avgPrice"), "event": etype}
                            asyncio.create_task(review_trade_async(sym, sd, ctx, to_telegram=True))
                        except Exception as e:
                            logger.debug({"event":"ws.ai_review_skip", "err": str(e)})
        except Exception as e:
            WS_ERRORS_TOTAL.labels("hook").inc()
            logger.warning({"event":"ws.hook_error", "error": str(e)})

async def _ws_loop():
    global _running, _listen_key
    if websockets is None:
        logger.warning({"event":"ws.module_missing", "hint":"pip install websockets"})
        return

    backoff = float(os.getenv("USER_STREAM_RECONNECT_BACKOFF","3.0"))
    backoff_max = float(os.getenv("USER_STREAM_RECONNECT_MAX_BACKOFF","60.0"))
    while _running:
        try:
            if not _listen_key:
                _listen_key = await _get_listen_key()
                if not _listen_key:
                    WS_ERRORS_TOTAL.labels("listenkey").inc()
                    await asyncio.sleep(_jitter(backoff))
                    backoff = min(backoff * 1.6, backoff_max)
                    continue

            url = f"{_BINANCE_FAPI}/ws/{_listen_key}"
            if _sample_ok():
                logger.debug({"event":"ws.connecting", "url": url})
            WS_UP.set(0)
            ws_note_up(False)
            async with websockets.connect(url, ping_interval=20, ping_timeout=20, close_timeout=10) as ws:
                WS_UP.set(1)
                ws_note_up(True)
                backoff = float(os.getenv("USER_STREAM_RECONNECT_BACKOFF","3.0"))
                ka_task = asyncio.create_task(_keepalive_loop())
                try:
                    async for raw in ws:
                        try:
                            msg = json.loads(raw)
                        except Exception:
                            continue
                        await _handle_event(msg)
                finally:
                    try: ka_task.cancel()
                    except: pass
        except Exception as e:
            WS_ERRORS_TOTAL.labels("ws").inc()
            logger.warning({"event":"ws.error", "error": str(e)})
        finally:
            WS_UP.set(0)
            ws_note_up(False)
            ws_note_reconnect()
            await asyncio.sleep(_jitter(backoff))
            backoff = min(backoff * 1.6, backoff_max)
            _listen_key = None  # מביאים listenKey חדש אחרי שגיאת WS

# ====== Public API ======
def start():
    """Sync wrapper: מפעיל את לולאת ה-WS כ-task; נופל רך אם חסר websockets."""
    global _running, _task
    if _running:
        return
    if os.getenv("USER_STREAM_ENABLE","0").lower() not in ("1","true","on","yes"):
        logger.info({"event":"ws.disabled_env"})
        return
    _running = True
    loop = asyncio.get_event_loop()
    _task = loop.create_task(_ws_loop())
    logger.info({"event":"ws.started"})

async def start_async():
    start()

async def stop_async():
    """עוצר בעדינות את ה-WS."""
    global _running, _task
    _running = False
    if _task:
        try:
            _task.cancel()
        except: pass
    logger.info({"event":"ws.stopped"})

