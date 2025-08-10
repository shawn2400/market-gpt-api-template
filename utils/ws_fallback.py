# utils/ws_fallback.py
import asyncio
import json
import logging
import time
from typing import Dict, List, Optional

import aiohttp

BINANCE_WS_URL = "wss://fstream.binance.com/stream?streams="
BINANCE_REST_PRICE = "https://fapi.binance.com/fapi/v1/ticker/price?symbol={symbol}"

class BinanceWSManager:
    def __init__(self, symbols: List[str]):
        self.symbols = [s.lower() for s in symbols]
        self.ws = None
        self.connected = False
        self._lock = asyncio.Lock()
        self._prices: Dict[str, float] = {}
        self._ts: Dict[str, float] = {}
        self._stop = False

    async def _rest_price(self, session: aiohttp.ClientSession, symbol: str) -> Optional[float]:
        try:
            url = BINANCE_REST_PRICE.format(symbol=symbol.upper())
            async with session.get(url, timeout=5) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return float(data["price"])
                else:
                    logging.warning(f"[ws_fallback] REST price HTTP {resp.status} for {symbol}")
        except Exception as e:
            logging.debug(f"[ws_fallback] REST price error for {symbol}: {e}")
        return None

    async def connect(self):
        backoff = 1.0
        while not self._stop:
            try:
                streams = "/".join(f"{s}@bookTicker" for s in self.symbols)
                url = BINANCE_WS_URL + streams
                async with aiohttp.ClientSession() as session:
                    logging.info(f"[ws_fallback] Connecting WS: {url}")
                    async with session.ws_connect(url, heartbeat=30, timeout=15) as ws:
                        self.ws = ws
                        self.connected = True
                        backoff = 1.0
                        logging.info(f"[ws_fallback] WS connected for {len(self.symbols)} symbols")

                        async for msg in ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                data = json.loads(msg.data)
                                d = data.get("data") or {}
                                sym = str(d.get("s", "")).upper()
                                ask = d.get("a")
                                bid = d.get("b")
                                price = None
                                try:
                                    if ask: price = float(ask)
                                    elif bid: price = float(bid)
                                except Exception:
                                    price = None
                                if sym and price is not None:
                                    async with self._lock:
                                        self._prices[sym] = price
                                        self._ts[sym] = time.time()
                            elif msg.type == aiohttp.WSMsgType.ERROR:
                                logging.error(f"[ws_fallback] WS error: {msg.data}")
                                break
            except Exception as e:
                self.connected = False
                logging.warning(f"[ws_fallback] WS disconnect: {e}. Reconnecting in {backoff:.1f}s")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
            finally:
                self.connected = False
                self.ws = None
        logging.info("[ws_fallback] WS manager stopped")

    async def stop(self):
        self._stop = True
        if self.ws:
            await self.ws.close()

    async def get_price(self, symbol: str) -> Optional[float]:
        s = str(symbol).upper()
        async with self._lock:
            p = self._prices.get(s)
            ts = self._ts.get(s)
        if p is not None:
            return float(p)
        # REST fallback אם לא הגיע עדיין WS
        async with aiohttp.ClientSession() as session:
            p = await self._rest_price(session, s)
        if p is not None:
            async with self._lock:
                self._prices[s] = float(p)
                self._ts[s] = time.time()
        return p

    def is_fresh(self, symbol: str, max_age_sec: int = 10) -> bool:
        s = str(symbol).upper()
        t = self._ts.get(s)
        return bool(t and (time.time() - t) <= max_age_sec)

binance_ws_manager: BinanceWSManager | None = None

async def launch_multi_websocket(symbols: List[str]):
    global binance_ws_manager
    if binance_ws_manager is not None:
        return
    binance_ws_manager = BinanceWSManager([s.upper() for s in symbols])
    asyncio.create_task(binance_ws_manager.connect())

async def get_price(symbol: str) -> Optional[float]:
    global binance_ws_manager
    if binance_ws_manager is None:
        raise RuntimeError("WebSocket not started — call launch_multi_websocket(symbols) first")
    return await binance_ws_manager.get_price(symbol)

def is_price_fresh(symbol: str, max_age_sec: int = 10) -> bool:
    global binance_ws_manager
    if binance_ws_manager is None:
        return False
    return binance_ws_manager.is_fresh(symbol, max_age_sec=max_age_sec)









