# routes/ws_stream.py
from __future__ import annotations

import os
import json
import time
import asyncio
import logging
import traceback
from typing import Any, Dict, List, Optional, Tuple, Set

import httpx
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

# ספריית websockets היא ה־WS client. ודא שהיא מותקנת (pip install websockets)
import websockets
from websockets.exceptions import ConnectionClosed, ConnectionClosedError, ConnectionClosedOK

router = APIRouter(prefix="/ws", tags=["WebSocket"])

# ==================== Config / Env ====================
LOG = logging.getLogger("algogpt.ws_stream")

FAPI_HOST = os.getenv("BINANCE_FAPI_HOST", "fstream.binance.com").strip()
WS_BASE = f"wss://{FAPI_HOST}"
REST_BASE = f"https://{FAPI_HOST}"

# Streams:
# markPrice@1s או aggTrade; אפשר לבחור דרך WS_MARKET_KIND=mark|agg
MARKET_KIND = (os.getenv("WS_MARKET_KIND") or "mark").strip().lower()
# mark = @markPrice@1s ; agg = @aggTrade
if MARKET_KIND not in ("mark", "agg"):
    MARKET_KIND = "mark"

# keepalive listenKey:
LISTENKEY_KEEPALIVE_SEC = int(os.getenv("WS_KEEPALIVE_SEC", "25") or 25)  # keep WS ping to Binance
# listenKey REST keepalive (Binance דורשים כל ~30 דק); נריץ כל 20 דק ברירת מחדל
LISTENKEY_REFRESH_SEC = int(os.getenv("LISTENKEY_REFRESH_SEC", "1200") or 1200)

API_KEY = (os.getenv("BINANCE_API_KEY") or "").strip()
API_SECRET = (os.getenv("BINANCE_API_SECRET") or "").strip()

# נשתמש בטוקן ה־Bearer שכבר קיים אצלך כדי לירות ל-/ops/trade-event
API_BEARER_TOKEN = (os.getenv("API_BEARER_TOKEN") or os.getenv("API_TOKEN") or "").strip()

# INTERNAL base – תואם למה שהגדרת ב-main.py
def _get_internal_base() -> str:
    internal = (os.getenv("INTERNAL_BASE") or "").strip().rstrip("/")
    if internal:
        return internal
    port = int(os.getenv("PORT", "10000") or "10000")
    return f"http://127.0.0.1:{port}"

INTERNAL_BASE = _get_internal_base()

# ==================== Helpers ====================

def _stream_suffix_for_symbol(sym: str) -> str:
    s = sym.lower()
    if MARKET_KIND == "mark":
        # Mark price 1s updates
        return f"{s}@markPrice@1s"
    # aggTrade
    return f"{s}@aggTrade"

def _combined_stream_url(symbols: List[str]) -> str:
    # https://binance-docs.github.io/apidocs/futures/en/#websocket-market-streams
    parts = [_stream_suffix_for_symbol(s) for s in symbols]
    stream = "/".join(parts)
    return f"{WS_BASE}/stream?streams={stream}"

async def _http_client() -> httpx.AsyncClient:
    cli = httpx.AsyncClient(timeout=httpx.Timeout(15.0))
    return cli

async def _post_trade_event(payload: Dict[str, Any]) -> None:
    """
    ירי פנימי ל־/ops/trade-event אצלך כדי להפעיל טלגרם/אוטומציות.
    """
    if not API_BEARER_TOKEN:
        return
    url = f"{INTERNAL_BASE}/ops/trade-event"
    headers = {"Authorization": f"Bearer {API_BEARER_TOKEN}", "Content-Type": "application/json"}
    try:
        async with await _http_client() as cli:
            await cli.post(url, headers=headers, content=json.dumps(payload, ensure_ascii=False))
    except Exception as e:
        LOG.warning("post_trade_event_failed: %s", e)

# ==================== Binance User Data (listenKey) ====================

class UserStream:
    """
    מנהל listenKey (יצירה/רענון) וחיבור WS להזנת ORDER_TRADE_UPDATE.
    """
    def __init__(self) -> None:
        self.listen_key: Optional[str] = None
        self._stop = asyncio.Event()
        self._refresh_task: Optional[asyncio.Task] = None
        self._conn_task: Optional[asyncio.Task] = None

    async def _create_listen_key(self) -> Optional[str]:
        if not API_KEY or not API_SECRET:
            LOG.warning("UserStream: missing api key/secret")
            return None
        url = f"https://{FAPI_HOST}/fapi/v1/listenKey"
        headers = {"X-MBX-APIKEY": API_KEY}
        try:
            async with await _http_client() as cli:
                r = await cli.post(url, headers=headers)
                if r.status_code == 200:
                    lk = r.json().get("listenKey")
                    LOG.info("UserStream: got listenKey")
                    return lk
                LOG.warning("UserStream: create listenKey bad_status=%s body=%s", r.status_code, r.text)
        except Exception as e:
            LOG.warning("UserStream: create listenKey failed: %s", e)
        return None

    async def _keepalive_listen_key(self) -> None:
        if not self.listen_key:
            return
        url = f"https://{FAPI_HOST}/fapi/v1/listenKey"
        headers = {"X-MBX-APIKEY": API_KEY}
        data = {"listenKey": self.listen_key}
        try:
            async with await _http_client() as cli:
                r = await cli.put(url, headers=headers, data=data)
                if r.status_code != 200:
                    LOG.warning("UserStream: keepalive bad_status=%s %s", r.status_code, r.text)
        except Exception as e:
            LOG.warning("UserStream: keepalive failed: %s", e)

    async def _run_keepalive_loop(self) -> None:
        """
        רענון listenKey כל LISTENKEY_REFRESH_SEC.
        """
        if not self.listen_key:
            return
        try:
            while not self._stop.is_set():
                await asyncio.sleep(LISTENKEY_REFRESH_SEC)
                await self._keepalive_listen_key()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            LOG.warning("UserStream.keepalive.loop error: %s", e)

    async def _handle_order_trade_update(self, obj: Dict[str, Any]) -> None:
        """
        מפענח ORDER_TRADE_UPDATE ושולח ל-/ops/trade-event + מחזיר dict משוטח.
        """
        try:
            o = obj.get("o", {})  # order update data
            s = str(o.get("s", "")).upper()       # symbol
            S = str(o.get("S", "")).upper()       # side BUY/SELL
            X = str(o.get("X", "")).upper()       # current order status
            x = str(o.get("x", "")).upper()       # execution type (TRADE, NEW, CANCELED, EXPIRED, ...)
            avg_px = float(o.get("ap") or 0)      # average price
            last_px = float(o.get("L") or 0)      # last filled price
            last_qty = float(o.get("l") or 0)     # last filled qty
            q = float(o.get("q") or 0)            # original qty
            z = float(o.get("z") or 0)            # cumulative filled qty
            clid = o.get("c")                     # clientOrderId
            oid = o.get("i")                      # orderId
            ps = str(o.get("ps", "")).upper()     # positionSide LONG/SHORT/BOTH
            rp = float(o.get("rp") or 0)          # realized pnl

            event_name = "ORDER_TRADE_UPDATE"
            desc = f"{x}/{X}"
            payload = {
                "event": event_name,
                "symbol": s,
                "side": S,
                "desc": desc,
                "extra": {
                    "status": X,
                    "execType": x,
                    "avgPrice": avg_px,
                    "lastPrice": last_px,
                    "lastQty": last_qty,
                    "cumQty": z,
                    "origQty": q,
                    "clientOrderId": clid,
                    "orderId": oid,
                    "positionSide": ps,
                    "realizedPnL": rp,
                }
            }
            # מחיר/כמויות לקיצור
            if last_px > 0:
                payload["price"] = last_px
            elif avg_px > 0:
                payload["price"] = avg_px
            if last_qty > 0:
                payload["qty"] = last_qty

            # ירי לאוטומציה (טלגרם וכו')
            await _post_trade_event(payload)

        except Exception as e:
            LOG.warning("handle_order_trade_update.failed: %s", e)

    async def _conn_loop(self, ws_out_queue: asyncio.Queue) -> None:
        """
        לולאת WS למפתח listenKey. שולח הודעות גולמיות גם ללקוח (ws_out_queue),
        וגם מפענח ORDER_TRADE_UPDATE ל-/ops/trade-event.
        """
        backoff = 1.0
        while not self._stop.is_set():
            if not self.listen_key:
                self.listen_key = await self._create_listen_key()
                if not self.listen_key:
                    await asyncio.sleep(min(backoff, 20.0))
                    backoff = min(backoff * 2, 20.0)
                    continue
                # אתחול משימות keepalive לרענון listenKey
                if not self._refresh_task or self._refresh_task.done():
                    self._refresh_task = asyncio.create_task(self._run_keepalive_loop())
            url = f"{WS_BASE}/ws/{self.listen_key}"
            try:
                async with websockets.connect(url, ping_interval=LISTENKEY_KEEPALIVE_SEC, max_size=2**20) as ws:
                    LOG.info("UserStream: connected to %s", url)
                    backoff = 1.0
                    while not self._stop.is_set():
                        raw = await ws.recv()
                        # שלח ללקוח
                        await ws_out_queue.put(raw)

                        # פרסינג להזנת אוטומציה
                        try:
                            msg = json.loads(raw)
                            if msg.get("e") == "ORDER_TRADE_UPDATE":
                                await self._handle_order_trade_update(msg)
                        except Exception:
                            pass
            except (ConnectionClosed, ConnectionClosedError, ConnectionClosedOK) as e:
                LOG.warning("UserStream: WS closed: %s", e)
            except Exception as e:
                LOG.warning("UserStream: conn error: %s", e)
            await asyncio.sleep(min(backoff, 10.0))
            backoff = min(backoff * 1.7, 10.0)

    async def start(self, ws_out_queue: asyncio.Queue) -> None:
        if self._conn_task and not self._conn_task.done():
            return
        self._stop.clear()
        self._conn_task = asyncio.create_task(self._conn_loop(ws_out_queue))

    async def stop(self) -> None:
        self._stop.set()
        if self._conn_task:
            self._conn_task.cancel()
            with contextlib.suppress(Exception):
                await self._conn_task
        if self._refresh_task:
            self._refresh_task.cancel()
            with contextlib.suppress(Exception):
                await self._refresh_task

# ==================== Market Streams ====================

class MarketStream:
    """
    מנהל חיבור WS משולב לסימבולים מרובים (markPrice@1s או aggTrade) + auto-resubscribe.
    """
    def __init__(self, symbols: List[str]) -> None:
        self.symbols = [s.upper() for s in symbols if s.strip()]
        self._stop = asyncio.Event()
        self._conn_task: Optional[asyncio.Task] = None

    async def _conn_loop(self, ws_out_queue: asyncio.Queue) -> None:
        if not self.symbols:
            return
        url = _combined_stream_url(self.symbols)
        backoff = 1.0
        while not self._stop.is_set():
            try:
                async with websockets.connect(url, ping_interval=LISTENKEY_KEEPALIVE_SEC, max_size=2**21) as ws:
                    LOG.info("MarketStream: connected to %s", url)
                    backoff = 1.0
                    while not self._stop.is_set():
                        raw = await ws.recv()
                        # פורמט combined-stream: {"stream": "...", "data": {...}}
                        # נשלח ללקוח כמו שהוא. אפשר גם לשטח אם רוצים.
                        await ws_out_queue.put(raw)
            except (ConnectionClosed, ConnectionClosedError, ConnectionClosedOK) as e:
                LOG.warning("MarketStream: WS closed: %s", e)
            except Exception as e:
                LOG.warning("MarketStream: conn error: %s", e)
            await asyncio.sleep(min(backoff, 10.0))
            backoff = min(backoff * 1.7, 10.0)

    async def start(self, ws_out_queue: asyncio.Queue) -> None:
        if self._conn_task and not self._conn_task.done():
            return
        self._stop.clear()
        self._conn_task = asyncio.create_task(self._conn_loop(ws_out_queue))

    async def stop(self) -> None:
        self._stop.set()
        if self._conn_task:
            self._conn_task.cancel()
            with contextlib.suppress(Exception):
                await self._conn_task


# ==================== WS endpoints ====================

@router.websocket("/stream")
async def ws_stream(ws: WebSocket):
    """
    מרקט סטרים אמיתי ל־Binance.
    דוגמה:  ws://host/ws/stream?symbols=BTCUSDT,ETHUSDT
    סוג העדכון נשלט ע"י WS_MARKET_KIND=mark|agg (ברירת מחדל markPrice@1s).
    """
    await ws.accept()
    try:
        symbols_param = ws.query_params.get("symbols", "")
        symbols = [s.strip().upper() for s in symbols_param.split(",") if s.strip()]
        if not symbols:
            await ws.send_text(json.dumps({"ok": False, "error": "missing symbols"}))
            await ws.close()
            return

        out_q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        stream = MarketStream(symbols)
        await stream.start(out_q)

        # loop: forward messages to client; client->server pings ignored
        while True:
            # עדיף לצרוך בשני הצדדים: גם מה־out_q (הודעות מרקט) וגם מהלקוח (ל-heartbeat אם צריך)
            done, pending = await asyncio.wait(
                [
                    asyncio.create_task(out_q.get()),
                    asyncio.create_task(ws.receive_text())
                ],
                return_when=asyncio.FIRST_COMPLETED
            )
            for t in done:
                try:
                    data = t.result()
                except Exception:
                    continue
                # אם זה הגיע מהלקוח (טקסט), נתעלם (משמש heartbeat של הדפדפן)
                if isinstance(data, str) and data.startswith("{") and ("stream" in data or "data" in data):
                    # מה־Binance → לקוח
                    await ws.send_text(data)
                else:
                    # ייתכן שהלקוח שלח טקסט פשוט "ping"
                    pass

    except WebSocketDisconnect:
        pass
    except Exception as e:
        LOG.warning("ws_stream error: %s", e)
    finally:
        with contextlib.suppress(Exception):
            await ws.close()


@router.websocket("/user")
async def ws_user(ws: WebSocket):
    """
    חיבור WS פרטי (User Data Stream) ל־Binance:
    - מתחבר אוטומטית עם listenKey (דורש BINANCE_API_KEY/SECRET).
    - מזרים את הודעות ה־USER ללקוח (raw JSON).
    - ממפה ORDER_TRADE_UPDATE → /ops/trade-event (טלגרם/אוטומציה).
    """
    await ws.accept()
    if not API_KEY or not API_SECRET:
        await ws.send_text(json.dumps({"ok": False, "error": "missing_api_keys"}))
        await ws.close()
        return

    out_q: asyncio.Queue = asyncio.Queue(maxsize=1000)
    u = UserStream()
    await u.start(out_q)

    try:
        while True:
            done, pending = await asyncio.wait(
                [
                    asyncio.create_task(out_q.get()),
                    asyncio.create_task(ws.receive_text())  # heartbeat/pings from client
                ],
                return_when=asyncio.FIRST_COMPLETED
            )
            for t in done:
                try:
                    data = t.result()
                except Exception:
                    continue
                # data כאן הוא raw JSON string מה־Binance
                if isinstance(data, str):
                    await ws.send_text(data)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        LOG.warning("ws_user error: %s", e)
    finally:
        with contextlib.suppress(Exception):
            await ws.close()
        with contextlib.suppress(Exception):
            await u.stop()

# ==================== Utilities ====================
import contextlib  # נדרש לסגירות שקטות


