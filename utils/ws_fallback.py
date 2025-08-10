# utils/ws_fallback.py
# WS מרובה-סטרימים לבינאנס (Futures), עם קאש מחירים טרי + גיבוי REST סינכרוני ל-klines.
import asyncio
import json
import time
import logging
from typing import Dict, List, Optional

import aiohttp
import requests
import pandas as pd

from utils import config

BINANCE_WS_BASE = getattr(config, "BINANCE_FUTURES_WS_BASE", "wss://fstream.binance.com")
STREAM_SUFFIX   = getattr(config, "BINANCE_WS_STREAM_SUFFIX", "/stream?streams=")
BINANCE_WS_URL_PREFIX = f"{BINANCE_WS_BASE}{STREAM_SUFFIX}"

FAPI_HTTP = getattr(config, "BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com")
SPOT_HTTP = getattr(config, "BINANCE_SPOT_HTTP_BASE", "https://api.binance.com")

# כמה זמן מחיר נחשב "טרי"
DEFAULT_MAX_AGE_SEC = int(getattr(config, "PRICE_MAX_AGE_SEC", 10))

_UA = {"User-Agent": "AlgoGPT/2 (Render) ws_fallback", "Accept": "application/json"}

class BinanceWSManager:
    def __init__(self, symbols: List[str]):
        self.symbols = [str(s).lower() for s in symbols if s]
        self.ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._session: Optional[aiohttp.ClientSession] = None
        self.prices: Dict[str, float] = {}
        self.ts: Dict[str, float] = {}
        self.connected: bool = False
        self._lock = asyncio.Lock()
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers=_UA,
                trust_env=True,  # מאפשר שימוש ב-HTTP(S)_PROXY מהסביבה
            )
        return self._session

    async def _run(self):
        backoff = 0.6
        while not self._stop.is_set():
            streams = "/".join(f"{s}@bookTicker" for s in self.symbols)
            url = BINANCE_WS_URL_PREFIX + streams
            try:
                session = await self._ensure_session()
                async with session.ws_connect(url, heartbeat=20) as ws:
                    self.ws = ws
                    self.connected = True
                    backoff = 0.6  # אפס את הבאק-אוף אחרי התחברות מוצלחת
                    logging.info(f"[ws_fallback] WS connected for {len(self.symbols)} symbols")
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            try:
                                data = json.loads(msg.data)
                                payload = data.get("data") or {}
                                symbol = str(payload.get("s") or "").upper()
                                ask = payload.get("a")
                                if symbol and ask is not None:
                                    price = float(ask)
                                    async with self._lock:
                                        self.prices[symbol] = price
                                        self.ts[symbol] = time.time()
                            except Exception as e:
                                logging.debug(f"[ws_fallback] parse error: {e}")
                        elif msg.type == aiohttp.WSMsgType.ERROR:
                            logging.error(f"[ws_fallback] WS error: {msg.data}")
                            break
            except Exception as e:
                self.connected = False
                d = min(10.0, backoff)
                logging.warning(f"[ws_fallback] WS connect/reconnect failed: {e} → sleep {d:.2f}s")
                await asyncio.sleep(d)
                backoff = min(10.0, backoff * 2.0)
                continue
            # נפלנו מהלולאה (סגירה רגילה) – ננסה להתחבר מחדש
            self.connected = False
            await asyncio.sleep(1.0)

    def start(self):
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run())

    async def stop(self):
        self._stop.set()
        if self.ws is not None:
            try:
                await self.ws.close()
            except Exception:
                pass
        if self._task:
            try:
                await self._task
            except Exception:
                pass
        if self._session is not None and not self._session.closed:
            try:
                await self._session.close()
            except Exception:
                pass
        self.connected = False

    async def get_price(self, symbol: str) -> Optional[float]:
        sym = str(symbol).upper()
        async with self._lock:
            return self.prices.get(sym)

    async def is_fresh(self, symbol: str, max_age_sec: int = DEFAULT_MAX_AGE_SEC) -> bool:
        sym = str(symbol).upper()
        now = time.time()
        async with self._lock:
            t = self.ts.get(sym)
        if not t:
            return False
        return (now - t) <= max_age_sec

# סינגלטון
binance_ws_manager: Optional[BinanceWSManager] = None

async def launch_multi_websocket(symbols: List[str]):
    global binance_ws_manager
    if binance_ws_manager is None:
        binance_ws_manager = BinanceWSManager(symbols)
        binance_ws_manager.start()

async def get_price(symbol: str) -> Optional[float]:
    global binance_ws_manager
    if binance_ws_manager is None:
        logging.debug("[ws_fallback] get_price called before WS start")
        return None
    return await binance_ws_manager.get_price(symbol)

def is_price_fresh(symbol: str, max_age_sec: int = DEFAULT_MAX_AGE_SEC) -> bool:
    """
    גרסה סינכרונית עבור קוד שלא רץ ב־async: משתמשים בטיימסטמפ ששמרנו.
    """
    global binance_ws_manager
    if binance_ws_manager is None:
        return False
    sym = str(symbol).upper()
    t = binance_ws_manager.ts.get(sym) if binance_ws_manager.ts else None
    if not t:
        return False
    return (time.time() - t) <= max_age_sec

# ---------- REST snapshot (סינכרוני) ל-klines עבור גיבוי מהיר ----------
def _rest_klines(
    market: str, symbol: str, interval: str, limit: int = 120,
    start_time: Optional[int] = None, end_time: Optional[int] = None,
    timeout: float = 10.0, retries: int = 3, backoff: float = 0.6
):
    base = FAPI_HTTP if market == "futures" else SPOT_HTTP
    path = "/fapi/v1/klines" if market == "futures" else "/api/v3/klines"
    url = base + path

    params = {"symbol": symbol.upper(), "interval": interval, "limit": int(limit)}
    if start_time: params["startTime"] = int(start_time)
    if end_time:   params["endTime"] = int(end_time)

    last = None
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, params=params, timeout=timeout, headers=_UA)
            if r.status_code == 200:
                return r.json()
            # CloudFront / WAF
            if r.status_code in (403, 418, 429, 503):
                d = min(10.0, backoff * (2 ** attempt))
                logging.warning(f"[ws_fallback] REST klines {symbol}@{interval} http={r.status_code} → sleep {d:.2f}s")
                time.sleep(d)
                last = r.text
                continue
            r.raise_for_status()
        except Exception as e:
            d = min(10.0, backoff * (2 ** attempt))
            logging.warning(f"[ws_fallback] REST klines network err (attempt {attempt+1}/{retries+1}) {symbol}@{interval}: {e} → {d:.2f}s")
            time.sleep(d)
            last = e
    if last:
        logging.error(f"[ws_fallback] REST klines failed for {symbol}@{interval}: {last}")
    return None

def snapshot_klines_df(
    symbol: str,
    interval: str = "15m",
    limit: int = 120,
    market_type: str = "futures",
) -> pd.DataFrame:
    """
    גיבוי מהיר לקריאת klines בלי תלות ב־python-binance.
    מחזיר DataFrame עם timestamp/open/high/low/close/volume (UTC index).
    """
    try:
        raw = _rest_klines(market_type, symbol, interval, limit=limit)
        if not raw or len(raw) < 5:
            return pd.DataFrame()

        df = pd.DataFrame(raw, columns=[
            "timestamp", "open", "high", "low", "close", "volume",
            "close_time", "quote_asset_volume", "number_of_trades",
            "taker_buy_base_volume", "taker_buy_quote_volume", "ignore"
        ])[["timestamp", "open", "high", "low", "close", "volume"]].copy()

        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        for col in ("open", "high", "low", "close", "volume"):
            df[col] = pd.to_numeric(df[col], errors="coerce")

        df.sort_values("timestamp", inplace=True)
        df.drop_duplicates(subset=["timestamp"], keep="last", inplace=True)
        df.dropna(inplace=True)
        df.set_index("timestamp", inplace=True)
        return df
    except Exception as e:
        logging.error(f"[ws_fallback] snapshot_klines_df error {symbol}@{interval}: {e}")
        return pd.DataFrame()












