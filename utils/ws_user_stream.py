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

WS_EVENTS_TOTAL = Counter("ws_user_events_total", "User-Stream events", ["type"])
WS_ERRORS_TOTAL = Counter("ws_user_errors_total", "User-Stream errors", ["stage"])
WS_UP = Gauge("ws_user_up", "Is WS user stream up (1/0)")

_BINANCE_FAPI = os.getenv("BINANCE_FUTURES_WS_BASE", "wss://fstream.binance.com").rstrip("/")
_BINANCE_HTTP = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com").rstrip("/")

LISTENKEY_KEEPALIVE_SEC = int(os.getenv("LISTENKEY_KEEPALIVE_SEC", "1800"))
ORDER_EVENT_RATE_LIMIT  = int(os.getenv("ORDER_EVENT_RATE_LIMIT", "15"))
LOG_SAMPLE_N            = int(os.getenv("LOG_SAMPLE_N", "20"))

_running = False
_task: Optional[asyncio.Task] = None
_listen_key: Optional[str] = None
_last_sample = 0
_seen_event_ids: Dict[str,bool] = {}
_seen_cap = 4096

def _sample_ok() -> bool:
    global _last_sample
    _last_sample += 1
    return (_last_sample % max(1, LOG_SAMPLE_N)) == 0

async def _get_listen_key() -> Optional[str]:
    api_key = os.getenv("BINANCE_API_KEY","").strip()
    if not api_key:
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
    etype = (msg.get("e") or msg.get("eventType") or "").upper()
    if not etype:
        # REST gateway or unknown format
        if "e" in msg:
            etype = str(msg["e"]).upper()
        else:
            etype = "UNKNOWN"
    WS_EVENTS_TOTAL.labels(etype).inc()
    if _sample_ok():
        logger.debug({"event":"ws.recv", "etype": etype})

    if etype in ("ORDER_TRADE_UPDATE","ORDER_UPDATE","ACCOUNT_UPDATE"):
        # Idempotency (transactionId / orderId / eventTime)
        uniq = str(msg.get("E") or msg.get("T") or msg.get("t") or json.dumps(msg, sort_keys=True)[:64])
        if uniq in _seen_event_ids:
            return
        _seen_event_ids[uniq] = True
        if len(_seen_event_ids) > _seen_cap:
            _seen_event_ids.clear()

        # Hook: על סגירת טרייד — אפשר להזניק AI review, אם תרצה
        try:
            if etype in ("ORDER_TRADE_UPDATE","ORDER_UPDATE"):
                o = msg.get("o") or msg.get("order") or {}
                status = (o.get("X") or o.get("orderStatus") or "").upper()
                if status in ("FILLED","CANCELED","EXPIRED"):
                    # דוגמה קצרה: קריאה רכה לביקורת
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

    backoff = 3.0
    while _running:
        try:
            if not _listen_key:
                _listen_key = await _get_listen_key()
                if not _listen_key:
                    WS_ERRORS_TOTAL.labels("listenkey").inc()
                    await asyncio.sleep(_jitter(backoff))
                    backoff = min(backoff * 1.6, 60.0)
                    continue

            url = f"{_BINANCE_FAPI}/ws/{_listen_key}"
            if _sample_ok():
                logger.debug({"event":"ws.connecting", "url": url})
            WS_UP.set(0)
            async with websockets.connect(url, ping_interval=20, ping_timeout=20, close_timeout=10) as ws:
                WS_UP.set(1)
                backoff = 3.0
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
            await asyncio.sleep(_jitter(backoff))
            backoff = min(backoff * 1.6, 60.0)
            # invalidate listenKey so we fetch a fresh one after hard errors
            _listen_key = None

async def start():
    global _running, _task
    if _running:
        return
    if os.getenv("USER_STREAM_ENABLE","0").lower() not in ("1","true","on","yes"):
        logger.info({"event":"ws.disabled_env"})
        return
    _running = True
    _task = asyncio.create_task(_ws_loop())
    logger.info({"event":"ws.started"})

async def stop():
    global _running, _task
    _running = False
    if _task:
        try:
            _task.cancel()
        except: pass
    logger.info({"event":"ws.stopped"})

def status() -> Dict[str, Any]:
    return {
        "running": bool(_running),
        "have_listen_key": bool(_listen_key),
        "ws_up": int(WS_UP._value.get() if hasattr(WS_UP, "_value") else 0),
    }

