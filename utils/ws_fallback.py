import asyncio
import json
import logging
import time
from typing import Dict, List, Optional

import aiohttp
import websockets

FAPI_WS = "wss://fstream.binance.com/stream"
FAPI_REST = "https://fapi.binance.com"
PING_INTERVAL = 20
RECONNECT_DELAY = 5
PRICE_TTL = 10  # שניות – מקס גיל מחיר ב-cache

_price_cache: Dict[str, float] = {}
_price_ts: Dict[str, float] = {}
_cache_lock = asyncio.Lock()

def _norm(symbol: str) -> str:
    return symbol.upper()

def _stream_path(symbols: List[str]) -> str:
    parts = [f"{s.lower()}@bookTicker" for s in symbols]
    return "/".join(parts)

async def _set_price(symbol: str, price: float):
    async with _cache_lock:
        s = _norm(symbol)
        _price_cache[s] = price
        _price_ts[s] = time.time()

async def _get_cached_price(symbol: str) -> Optional[float]:
    async with _cache_lock:
        s = _norm(symbol)
        p = _price_cache.get(s)
        ts = _price_ts.get(s)
    if p is None or ts is None:
        return None
    if time.time() - ts > PRICE_TTL:
        return None
    return p

async def _rest_price(session: aiohttp.ClientSession, symbol: str) -> Optional[float]:
    url = f"{FAPI_REST}/fapi/v1/ticker/price"
    try:
        async with session.get(url, params={"symbol": _norm(symbol)}, timeout=10) as r:
            if r.status != 200:
                logging.warning(f"[ws_fallback] REST price {symbol} status={r.status}")
                return None
            data = await r.json()
            price = float(data["price"])
            await _set_price(symbol, price)
            return price
    except Exception as e:
        logging.error(f"[ws_fallback] REST price error for {symbol}: {e}")
        return None

async def get_price(symbol: str) -> Optional[float]:
    p = await _get_cached_price(symbol)
    if p is not None:
        return p
    async with aiohttp.ClientSession() as session:
        return await _rest_price(session, symbol)

async def _ws_loop(symbols: List[str]):
    stream = _stream_path(symbols)
    url = f"{FAPI_WS}?streams={stream}"
    logging.info(f"[ws_fallback] Connecting WS: {url}")

    while True:
        try:
            async with websockets.connect(url, ping_interval=PING_INTERVAL, ping_timeout=10) as ws:
                logging.info("[ws_fallback] WS connected")
                while True:
                    msg = await ws.recv()
                    data = json.loads(msg)
                    payload = data.get("data") or data  # multi-stream
                    s = payload.get("s")
                    # bookTicker מחזיר ask/bid; ניקח ask כמחיר עדכני
                    a = payload.get("a")
                    if s and a:
                        try:
                            await _set_price(s, float(a))
                        except Exception:
                            pass
        except Exception as e:
            logging.error(f"[ws_fallback] WS error: {e}")
            await asyncio.sleep(RECONNECT_DELAY)
            logging.info("[ws_fallback] Reconnecting WS...")

async def launch_multi_websocket(symbols: List[str]):
    if not symbols:
        symbols = ["BTCUSDT"]
    uniq = sorted({ _norm(s) for s in symbols })
    asyncio.create_task(_ws_loop(uniq))
    logging.info(f"[ws_fallback] Multi-WS started for {len(uniq)} symbols: {uniq}")







