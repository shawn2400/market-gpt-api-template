# ws_stream.py
from __future__ import annotations

import os
import json
import time
import hmac
import asyncio
import logging
import random
import hashlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Callable

import httpx

try:
    import websockets
except Exception as _e:  # יופעל לוג בלבד, האפליקציה לא תקרוס
    websockets = None  # type: ignore

_log = logging.getLogger("algogpt.ws")


@dataclass
class WSConfig:
    api_key: str
    api_secret: str
    keepalive_sec: int = 1500  # Binance userData: 30 דקות, נרענן מוקדם
    market_streams: List[str] = field(default_factory=list)  # למשל: ["btcusdt@trade","btcusdt@markPrice@1s"]
    futures: bool = True  # FAPI (USDT-M)
    namespace: str = "ws"
    working_type: str = "MARK_PRICE"  # לא בשימוש ישיר כאן אך נגיש חיצונית


class WSManager:
    """
    WS חי לבינאנס: userData + market streams (Futures כברירת מחדל).
    Auto-resubscribe, שמירת listenKey, keepalive, ו-backoff עם jitter.
    אין polling — הכול WS.
    """

    def __init__(self, cfg: WSConfig, http_client: Optional[httpx.AsyncClient] = None) -> None:
        self.cfg = cfg
        self._http = http_client or httpx.AsyncClient(timeout=httpx.Timeout(15.0))
        self._running = False
        self._user_task: Optional[asyncio.Task] = None
        self._market_task: Optional[asyncio.Task] = None
        self._keepalive_task: Optional[asyncio.Task] = None
        self._listen_key: Optional[str] = None
        self._close_evt = asyncio.Event()
        self._user_ws = None
        self._market_ws = None

        # Handlers (אפשר לחבר כאן ריצה ל־runtime policies)
        self.on_user_event: Callable[[Dict[str, Any]], None] = self._default_user_handler
        self.on_market_event: Callable[[Dict[str, Any]], None] = self._default_market_handler

    # ---------- Public API ----------

    async def run_forever(self) -> None:
        if websockets is None:
            _log.warning("websockets package not available; WS disabled.")
            return
        if self._running:
            return
        self._running = True
        self._close_evt.clear()

        # בונה listenKey ומרים את שני הערוצים + keepalive
        await self._ensure_listen_key()

        self._user_task = asyncio.create_task(self._user_loop())
        self._market_task = asyncio.create_task(self._market_loop())
        self._keepalive_task = asyncio.create_task(self._keepalive_loop())

        try:
            await self._close_evt.wait()
        finally:
            await self._graceful_close()

    async def close(self) -> None:
        self._running = False
        self._close_evt.set()

    # ---------- Internal: REST helpers ----------

    def _api_base(self) -> str:
        return "https://fapi.binance.com" if self.cfg.futures else "https://api.binance.com"

    async def _ensure_listen_key(self) -> None:
        """יוצר או מחזיר listenKey ל־userDataStream."""
        if not self.cfg.api_key or not self.cfg.api_secret:
            self._listen_key = None
            _log.warning("No API keys; user WS will be disabled.")
            return
        try:
            r = await self._http.post(
                f"{self._api_base()}/fapi/v1/listenKey" if self.cfg.futures else f"{self._api_base()}/api/v3/userDataStream",
                headers={"X-MBX-APIKEY": self.cfg.api_key},
            )
            data = r.json()
            self._listen_key = data.get("listenKey")
            if not self._listen_key:
                raise RuntimeError(f"listenKey missing: {data}")
            _log.info("Obtained listenKey.")
        except Exception as e:
            _log.warning("listenKey obtain failed: %s", e)
            self._listen_key = None  # user stream יושבת עד להצלחה

    async def _keepalive_loop(self) -> None:
        """שומר על listenKey בחיים; אם נכשל — מנסה להשיג חדש."""
        if not self.cfg.keepalive_sec or self.cfg.keepalive_sec < 60:
            self.cfg.keepalive_sec = 1500
        # נחדש 60–120 שניות לפני פקיעה
        sleep_sec = max(60, min(self.cfg.keepalive_sec - 90, 1740))
        while self._running:
            await asyncio.sleep(sleep_sec)
            if not self._running:
                break
            if not self._listen_key or not self.cfg.api_key:
                await self._ensure_listen_key()
                continue
            try:
                await self._http.put(
                    f"{self._api_base()}/fapi/v1/listenKey" if self.cfg.futures else f"{self._api_base()}/api/v3/userDataStream",
                    headers={"X-MBX-APIKEY": self.cfg.api_key},
                    params={"listenKey": self._listen_key},
                )
                _log.debug("listenKey keepalive OK.")
            except Exception as e:
                _log.warning("listenKey keepalive failed: %s; re-create…", e)
                await self._ensure_listen_key()

    # ---------- Internal: WS loops ----------

    def _ws_base(self) -> str:
        # Futures market/user
        return "wss://fstream.binance.com" if self.cfg.futures else "wss://stream.binance.com:9443"

    async def _user_loop(self) -> None:
        backoff = 1.0
        while self._running:
            if not self._listen_key:
                await asyncio.sleep(1.0)
                await self._ensure_listen_key()
                continue
            uri = f"{self._ws_base()}/ws/{self._listen_key}"
            try:
                _log.info("Connecting user WS: %s", uri)
                async with websockets.connect(uri, ping_interval=20, ping_timeout=20, close_timeout=5) as ws:
                    self._user_ws = ws
                    backoff = 1.0
                    async for msg in ws:
                        if not self._running:
                            break
                        try:
                            data = json.loads(msg)
                        except Exception:
                            continue
                        self.on_user_event(data)
            except Exception as e:
                _log.warning("user WS disconnected: %s", e)
                await asyncio.sleep(backoff + random.random())
                backoff = min(backoff * 2, 30.0)
            finally:
                self._user_ws = None

    async def _market_loop(self) -> None:
        backoff = 1.0
        streams = [s for s in self.cfg.market_streams if s]
        if not streams:
            _log.info("No market streams configured; skipping market WS.")
            return
        url = f"{self._ws_base()}/stream?streams=" + "/".join(streams)
        while self._running:
            try:
                _log.info("Connecting market WS: %s", url)
                async with websockets.connect(url, ping_interval=20, ping_timeout=20, close_timeout=5) as ws:
                    self._market_ws = ws
                    backoff = 1.0
                    async for msg in ws:
                        if not self._running:
                            break
                        try:
                            data = json.loads(msg)
                        except Exception:
                            continue
                        # market stream מגיע בפורמט {"stream": "...", "data": {...}}
                        payload = data.get("data", data)
                        self.on_market_event(payload)
            except Exception as e:
                _log.warning("market WS disconnected: %s", e)
                await asyncio.sleep(backoff + random.random())
                backoff = min(backoff * 2, 30.0)
            finally:
                self._market_ws = None

    async def _graceful_close(self) -> None:
        for ws in (self._user_ws, self._market_ws):
            if ws:
                try:
                    await ws.close()
                except Exception:
                    pass
        for t in (self._user_task, self._market_task, self._keepalive_task):
            if t and not t.done():
                t.cancel()
                try:
                    await t
                except Exception:
                    pass

    # ---------- Default handlers (ניתן להחלפה מבחוץ) ----------

    def _default_user_handler(self, evt: Dict[str, Any]) -> None:
        """
        דוגמה: קבלה של events כמו ACCOUNT_UPDATE, ORDER_TRADE_UPDATE, MARGIN_CALL
        כאן אפשר לחבר ל־/ops/trade-event או לטלגרם וכו'.
        """
        etype = evt.get("e") or evt.get("eventType") or "user_evt"
        try:
            _log.debug("USER EVT: %s", json.dumps(evt, ensure_ascii=False)[:600])
        except Exception:
            _log.debug("USER EVT: %s", etype)

    def _default_market_handler(self, evt: Dict[str, Any]) -> None:
        """
        דוגמה: trade / markPriceUpdate / kline וכו' — ללא polling.
        אפשר לנהל כאן מדיניות runtime (כיוונתי ל-env), או להאכיל cache/redis.
        """
        try:
            t = evt.get("e") or evt.get("eventType") or evt.get("E")
            _log.debug("MKT EVT: %s", json.dumps(evt, ensure_ascii=False)[:600])
        except Exception:
            _log.debug("MKT EVT (raw)")
