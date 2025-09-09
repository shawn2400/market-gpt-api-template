# utils/ws_user_stream.py
from __future__ import annotations
import os, time, json, hmac, hashlib, logging, asyncio
from typing import Optional, Dict, Any

import httpx

try:
    import websockets  # pip install websockets
except Exception:
    websockets = None  # המודול יתאפס כ"כבוי" אם אין תלות

# אינטגרציות (לא חובה—נשתמש אם קיימות)
try:
    from utils.trade_manager import handle_order_filled  # TP1/BE guard כבר שם
except Exception:
    async def handle_order_filled(_event: Dict[str, Any]):  # type: ignore
        return None

try:
    from utils.ai_reviewer import review_trade_async
except Exception:
    async def review_trade_async(_s, _d, _ctx, to_telegram=True):  # type: ignore
        return {"ok": False, "skipped": "ai_reviewer_missing"}

logger = logging.getLogger("algogpt.ws_user_stream")

# ====== ENV ======
HTTP_BASE = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com").rstrip("/")
WS_BASE   = os.getenv("BINANCE_FUTURES_WS_BASE", "wss://fstream.binance.com").rstrip("/")
API_KEY   = os.getenv("BINANCE_API_KEY", "").strip()
API_SEC   = os.getenv("BINANCE_API_SECRET", "").strip()

ENABLE    = os.getenv("USER_STREAM_ENABLE", "1").lower() in ("1","true","yes","on")
KEEPALIVE_SEC = int(os.getenv("LISTENKEY_KEEPALIVE_SEC", "1800"))
RECONNECT_BACKOFF = float(os.getenv("USER_STREAM_RECONNECT_BACKOFF", "3.0"))
MAX_BACKOFF = float(os.getenv("USER_STREAM_RECONNECT_MAX_BACKOFF", "60.0"))

# ====== STATE ======
_listen_key: Optional[str] = None
_task: Optional[asyncio.Task] = None
_keep_task: Optional[asyncio.Task] = None
_running = False
_last_event_ts: float = 0.0
_stats = {"events": 0, "order_updates": 0, "acct_updates": 0, "closes": 0, "errors": 0}

# ====== HTTP helpers ======
async def _get_listen_key() -> Optional[str]:
    if not API_KEY:
        logger.warning("USER-STREAM disabled: missing API key")
        return None
    url = f"{HTTP_BASE}/fapi/v1/listenKey"
    try:
        async with httpx.AsyncClient(timeout=10.0, headers={"X-MBX-APIKEY": API_KEY}) as cli:
            r = await cli.post(url)
            r.raise_for_status()
            lk = r.json().get("listenKey")
            return lk
    except Exception as e:
        logger.error("get listenKey failed: %s", e)
        return None

async def _keepalive_loop():
    global _listen_key
    while _running and _listen_key:
        try:
            await asyncio.sleep(KEEPALIVE_SEC - 30)
            async with httpx.AsyncClient(timeout=10.0, headers={"X-MBX-APIKEY": API_KEY}) as cli:
                r = await cli.put(f"{HTTP_BASE}/fapi/v1/listenKey", params={"listenKey": _listen_key})
                if not r.is_success:
                    logger.warning("listenKey keepalive non-200: %s %s", r.status_code, r.text)
        except Exception as e:
            logger.warning("listenKey keepalive failed: %s", e)

# ====== Event handling ======
async def _on_order_trade_update(payload: Dict[str, Any]):
    """ORDER_TRADE_UPDATE → נשתמש לשני דברים:
       1) להעביר ל-trade_manager לטובת BE/TP guard (יש כבר פונקציה).
       2) לזהות Fill/Close ולהזניק ביקורת AI (עדין/לא מעמיס).
    """
    _stats["order_updates"] += 1
    try:
        await handle_order_filled(payload.get("o", {}))
    except Exception:
        pass

    try:
        o = payload.get("o", {})
        symbol = str(o.get("s") or "").upper()
        side   = "LONG" if (o.get("S") == "BUY") else "SHORT"
        status = str(o.get("X") or o.get("x") or "").upper()  # X=current, x=execution
        reason = str(o.get("R") or o.get("r") or "")

        # Close detection (פשוט/עדין): order FILLED עם reduceOnly או סטטוס CANCELED/EXPIRED של TP/SL סופי
        reduce_only = bool(o.get("ro"))
        if status == "FILLED" and reduce_only:
            _stats["closes"] += 1
            ctx = {
                "reason": reason, "reduce_only": True,
                "pnl": o.get("rp"), "commission": o.get("n"),
                "entry": o.get("ap"), "price": o.get("L"), "qty": o.get("l"),
                "orderId": o.get("i"),
            }
            await review_trade_async(symbol, side, ctx, to_telegram=True)
    except Exception as e:
        logger.warning("order_update review hook failed: %s", e)

async def _on_account_update(payload: Dict[str, Any]):
    """ACCOUNT_UPDATE → זיהוי 'סגירת' פוזיציה דרך BUP ('P') כשהכמות יורדת ל-0."""
    _stats["acct_updates"] += 1
    try:
        # payload example fields: B=updateReason, P=positions(list of {s, pa, ep, cr, up, mt, iw, ps})
        poss = payload.get("P") or []
        for p in poss:
            symbol = str(p.get("s") or "").upper()
            amt = float(p.get("pa") or 0)
            if abs(amt) < 1e-12:
                _stats["closes"] += 1
                ctx = {
                    "reason": "position_closed",
                    "entry": p.get("ep"),
                    "pnl": p.get("up"),
                    "cross": p.get("cr"),
                }
                # אין לנו צד בטוח כאן—ננחש לפי סימן 'iw' או נשאיר 'BOTH'
                await review_trade_async(symbol, "BOTH", ctx, to_telegram=True)
    except Exception as e:
        logger.warning("account_update review hook failed: %s", e)

async def _dispatch(msg: Dict[str, Any]):
    global _last_event_ts
    _stats["events"] += 1
    _last_event_ts = time.time()
    et = (msg.get("e") or "").upper()
    if et == "ORDER_TRADE_UPDATE":
        await _on_order_trade_update(msg)
    elif et == "ACCOUNT_UPDATE":
        await _on_account_update(msg)

# ====== main WS loop ======
async def _ws_loop():
    global _listen_key
    if websockets is None:
        logger.warning("websockets package not installed; USER-STREAM disabled.")
        return

    backoff = RECONNECT_BACKOFF
    while _running:
        try:
            _listen_key = await _get_listen_key()
            if not _listen_key:
                await asyncio.sleep(backoff)
                backoff = min(MAX_BACKOFF, backoff * 1.5)
                continue

            url = f"{WS_BASE}/ws/{_listen_key}"
            logger.info({"event": "ws_user_stream_connecting", "url": url})
            async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
                backoff = RECONNECT_BACKOFF  # reset
                while _running:
                    raw = await ws.recv()
                    try:
                        msg = json.loads(raw)
                        await _dispatch(msg)
                    except Exception:
                        logger.debug("non-json ws message: %s", raw)
        except asyncio.CancelledError:
            break
        except Exception as e:
            _stats["errors"] += 1
            logger.warning({"event": "ws_user_stream_error", "error": str(e)})
            await asyncio.sleep(backoff)
            backoff = min(MAX_BACKOFF, backoff * 1.5)

# ====== public control API ======
def is_running() -> bool:
    return _running

def last_event_ts() -> float:
    return _last_event_ts

def get_stats() -> Dict[str, Any]:
    return {
        "running": _running,
        "last_event_ts": _last_event_ts,
        "listenKey": bool(_listen_key),
        "counters": dict(_stats),
        "ws_enabled": websockets is not None,
    }

def start() -> None:
    global _running, _task, _keep_task
    if _running:
        return
    if not ENABLE:
        logger.info("USER-STREAM disabled by env (USER_STREAM_ENABLE=0)")
        return
    _running = True
    loop = asyncio.get_event_loop()
    _task = loop.create_task(_ws_loop())
    _keep_task = loop.create_task(_keepalive_loop())
    logger.info({"event": "ws_user_stream_started"})

def stop() -> None:
    global _running, _task, _keep_task, _listen_key
    if not _running:
        return
    _running = False
    if _task: _task.cancel()
    if _keep_task: _keep_task.cancel()
    _task = None
    _keep_task = None
    _listen_key = None
    logger.info({"event": "ws_user_stream_stopped"})
