# utils/ws_fallback.py
import asyncio
import json
import logging
import time
from typing import Dict, List, Optional

import aiohttp
from utils import config

BINANCE_WS_BASE = config.BINANCE_FUTURES_WS_BASE  # "wss://fstream.binance.com"
STREAM_FMT = "/".join(["{sym}@bookTicker"])

class BinanceWSManager:
    """
    מנהל חיבור WS משותף ל־bookTicker עבור מספר סמלים.
    - שמירת מחיר אחרון + טיימסטמפ לכל סימבול
    - רה-קונקט אוטומטי עם backoff
    - thread-safe באמצעות asyncio.Lock
    """
    def __init__(self, symbols: List[str]):
        self.symbols = [s.lower() for s in symbols if s]
        self._prices: Dict[str, float] = {}
        self._ts: Dict[str, float] = {}
        self._lock = asyncio.Lock()
        self._running = False

    @property
    def streams_url(self) -> str:
        # combined streams API
        streams = "/".join(f"{s}@bookTicker" for s in self.symbols)
        return f"{BINANCE_WS_BASE}/stream?streams={streams}"

    async def connect_forever(self):
        """
        לולאת חיבור אינסופית עם רה־קונקט אוטומטי.
        """
        self._running = True
        backoff = 1.0
        while self._running:
            try:
                async with aiohttp.ClientSession() as session:
                    url = self.streams_url
                    logging.info(f"[ws_fallback] Connecting WS: {url}")
                    async with session.ws_connect(url, heartbeat=25) as ws:
                        logging.info(f"[ws_fallback] WS connected to Binance for {len(self.symbols)} symbols")
                        backoff = 1.0  # reset backoff on success
                        async for msg in ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                await self._handle_message(msg.data)
                            elif msg.type == aiohttp.WSMsgType.ERROR:
                                logging.error(f"[ws_fallback] WS error: {msg.data}")
                                break
            except Exception as e:
                logging.warning(f"[ws_fallback] WS disconnected: {e}. Reconnecting in {backoff:.1f}s…")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)

    async def _handle_message(self, data: str):
        try:
            obj = json.loads(data)
            payload = obj.get("data") or {}
            sym = (payload.get("s") or "").upper()
            # נעדיף ask (a) כ-entry שמרני
            ask = payload.get("a")
            if not sym or ask is None:
                return
            price = float(ask)
            now = time.time()
            async with self._lock:
                self._prices[sym] = price
                self._ts[sym] = now
        except Exception as e:
            logging.debug(f"[ws_fallback] parse error: {e}")

    async def get_price(self, symbol: str) -> Optional[float]:
        sym = (symbol or "").upper()
        async with self._lock:
            return self._prices.get(sym)

    async def get_price_with_ts(self, symbol: str) -> Optional[tuple[float, float]]:
        sym = (symbol or "").upper()
        async with self._lock:
            if sym in self._prices and sym in self._ts:
                return self._prices[sym], self._ts[sym]
            return None

    async def stop(self):
        self._running = False

# ====== ממשק גלובלי פשוט ======
_manager: Optional[BinanceWSManager] = None
_manager_task: Optional[asyncio.Task] = None

async def launch_multi_websocket(symbols: List[str]):
    """
    מפעיל WS פעם אחת לתהליך. קריאות נוספות יתעלמו.
    """
    global _manager, _manager_task
    if _manager_task and not _manager_task.done():
        logging.info("[ws_fallback] WS already running")
        return
    _manager = BinanceWSManager(symbols)
    _manager_task = asyncio.create_task(_manager.connect_forever())

async def get_price(symbol: str) -> Optional[float]:
    global _manager
    if _manager is None:
        raise RuntimeError("WebSocket not started. Call launch_multi_websocket([...]) first.")
    return await _manager.get_price(symbol)

def is_price_fresh(symbol: str, max_age_sec: int = config.PRICE_MAX_AGE_SEC) -> bool:
    """
    בודק ע״י הטיימסטמפ האחרון האם הדאטה טרייה.
    """
    global _manager
    if _manager is None:
        return False
    sym = (symbol or "").upper()
    ts = None
    # קריאה לא־אסינכרונית: משתמשים ישירות במבנה פנימי בצורה בטוחה מספיק לקריאה בלבד
    ts = _manager._ts.get(sym) if hasattr(_manager, "_ts") else None
    if ts is None:
        return False
    return (time.time() - ts) <= max_age_sec










