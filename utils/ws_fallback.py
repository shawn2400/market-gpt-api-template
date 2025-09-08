# utils/ws_fallback.py
from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from typing import Dict, Any, Optional, List

import httpx

LAST_PRICE_CACHE: Dict[str, Dict[str, Any]] = {}
logger = logging.getLogger("algogpt.ws")

def update_price(symbol: str, price: float) -> None:
    if not symbol:
        return
    try:
        p = float(price)
    except Exception:
        return
    if p <= 0:
        return
    LAST_PRICE_CACHE[symbol.upper()] = {"price": p, "ts": time.time()}

def get_price(symbol: str) -> Optional[float]:
    item = LAST_PRICE_CACHE.get(symbol.upper())
    return float(item["price"]) if item and "price" in item else None

def is_price_fresh(symbol: str, max_age_sec: int = 10) -> bool:
    info = LAST_PRICE_CACHE.get(symbol.upper())
    return bool(info and (time.time() - info.get("ts", 0.0)) <= max_age_sec)

async def auto_price_updater(
    symbols: List[str],
    *,
    ws_interval_keepalive: int = 25,
    rest_interval_sec: int = 15,
) -> None:
    syms = [s.upper() for s in symbols if isinstance(s, str) and s.strip()]
    if not syms:
        logger.warning({"event": "price_updater_empty_symbols"})
        return

    ws_task = None
    rest_task = None
    try:
        while True:
            try:
                if rest_task and not rest_task.done():
                    rest_task.cancel()
                ws_task = asyncio.create_task(
                    _ws_price_stream(syms, ping_interval=ws_interval_keepalive)
                )
                await ws_task
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error({"event": "ws_stream_error", "error": str(e)})

            try:
                rest_task = asyncio.create_task(
                    _rest_price_refresher_loop(syms, period=rest_interval_sec)
                )
                backoff = min(60, 5 + random.uniform(0, 3))
                await asyncio.sleep(backoff)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error({"event": "rest_fallback_error", "error": str(e)})
                await asyncio.sleep(5)
    finally:
        for t in (ws_task, rest_task):
            if t and not t.done():
                t.cancel()

async def _ws_price_stream(symbols: List[str], *, ping_interval: int = 25) -> None:
    import websockets  # type: ignore

    streams = "/".join(f"{s.lower()}@markPrice@1s" for s in symbols)
    url = f"wss://fstream.binance.com/stream?streams={streams}"

    backoff = 1.5
    while True:
        try:
            logger.info({"event": "ws_connecting", "url": url, "symbols": len(symbols)})
            async with websockets.connect(
                url,
                ping_interval=ping_interval,
                ping_timeout=10,
                close_timeout=5,
                max_size=1_000_000,
            ) as ws:
                backoff = 1.5
                last_ping = time.time()
                while True:
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=ping_interval + 5)
                        data = json.loads(msg)
                        d = data.get("data") or {}
                        sym = d.get("s")
                        price = d.get("p") or d.get("markPrice") or d.get("price")
                        if sym and price:
                            update_price(sym, float(price))
                        if (time.time() - last_ping) >= ping_interval:
                            try:
                                await ws.ping()
                            except Exception:
                                pass
                            last_ping = time.time()
                    except asyncio.TimeoutError:
                        try:
                            await ws.ping()
                            last_ping = time.time()
                        except Exception:
                            logger.warning({"event": "ws_ping_failed"})
                            break
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error({"event": "ws_connect_error", "error": str(e)})
            await asyncio.sleep(backoff + random.uniform(0, 0.8))
            backoff = min(backoff * 2, 60.0)

async def _rest_price_refresher_loop(symbols: List[str], *, period: int = 15) -> None:
    target = set(s.upper() for s in symbols)
    async with httpx.AsyncClient(
        timeout=8.0,
        headers={
            "User-Agent": "AlgoGPT/2 price-fallback",
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
        },
    ) as x:
        while True:
            try:
                r = await x.get("https://fapi.binance.com/fapi/v1/premiumIndex")
                if r.status_code == 200:
                    arr = r.json()
                    for o in arr:
                        sym = str(o.get("symbol") or "").upper()
                        if sym in target:
                            price = o.get("markPrice") or o.get("price")
                            try:
                                p = float(price)
                                if p > 0:
                                    update_price(sym, p)
                            except Exception:
                                continue
                elif r.status_code in (418, 429, 500, 502, 503, 504):
                    retry = int(r.headers.get("Retry-After", "2"))
                    await asyncio.sleep(min(30, max(2, retry)))
                else:
                    r.raise_for_status()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error({"event": "rest_fallback_iter_error", "error": str(e)})
            await asyncio.sleep(period)






























