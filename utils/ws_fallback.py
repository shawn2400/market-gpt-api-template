# utils/ws_fallback.py
# WS רב-סטרימים לבינאנס (Futures) + קאש מחירים טרי + REST Fallback זהיר עם מודעות-באן (418/429).
import asyncio
import json
import time
import logging
from typing import Dict, List, Optional, Iterable, Tuple

import aiohttp
import requests
import pandas as pd

from utils import config

BINANCE_WS_BASE = getattr(config, "BINANCE_FUTURES_WS_BASE", "wss://fstream.binance.com").rstrip("/")
STREAM_SUFFIX   = getattr(config, "BINANCE_WS_STREAM_SUFFIX", "/stream?streams=")
BINANCE_WS_URL_PREFIX = f"{BINANCE_WS_BASE}{STREAM_SUFFIX}"

FAPI_HTTP = getattr(config, "BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com").rstrip("/")
SPOT_HTTP = getattr(config, "BINANCE_SPOT_HTTP_BASE", "https://api.binance.com").rstrip("/")

# כמה זמן מחיר נחשב "טרי"
DEFAULT_MAX_AGE_SEC = int(getattr(config, "PRICE_MAX_AGE_SEC", 10))

# מגבלה קשיחה לצורך בטיחות (בינאנס: עד ~200 streams לחיבור)
MAX_STREAMS_PER_CONN = int(getattr(config, "MAX_STREAMS_PER_CONN", 200))

# UA סטנדרטי כדי להימנע מטריגרים של WAF/CloudFront (תוקן AppleWebKit/537.36)
_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "en-US,en;q=0.9",
}

def _norm_symbols(symbols: Iterable[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for s in symbols or []:
        u = str(s).strip().lower()
        if not u:
            continue
        if u not in seen:
            seen.add(u); out.append(u)
    # הקפאת כמות סטרימים בהתאם למגבלה (בטיחות)
    if len(out) > MAX_STREAMS_PER_CONN:
        logging.warning(f"[ws_fallback] truncating streams from {len(out)} to {MAX_STREAMS_PER_CONN}")
        out = out[:MAX_STREAMS_PER_CONN]
    return out

# ------- Ban-aware circuit breaker ל-REST -------
# נשמור כאן מתי נרשם 418/429/403/503 ונמנע נסיונות REST למשך cooldown.
# נעדיף Retry-After אם קיים; אחרת נשתמש בברירות-מחדל שמרניות.
_last_rest_ban_until_ts: float = 0.0  # epoch seconds עד מתי להימנע מ-REST
_default_cooldown_sec: int = int(getattr(config, "REST_COOLDOWN_SEC", 900))  # 15 דקות דיפולט
_max_cooldown_sec: int = int(getattr(config, "REST_MAX_COOLDOWN_SEC", 3600))  # שעה מקסימום

def _now() -> float:
    return time.time()

def _parse_retry_after(resp: requests.Response) -> Optional[int]:
    try:
        ra = resp.headers.get("Retry-After")
        if not ra:
            return None
        # יכול להיות מספר שניות או תאריך; נתמוך במספר שניות
        ra = ra.strip()
        if ra.isdigit():
            return int(ra)
    except Exception:
        return None
    return None

def _note_rest_ban(resp: Optional[requests.Response] = None):
    """ מעדכן את חלון ה־cooldown עבור REST לפי Retry-After (אם קיים) או דיפולט. """
    global _last_rest_ban_until_ts
    cooldown = _default_cooldown_sec
    if isinstance(resp, requests.Response):
        ra = _parse_retry_after(resp)
        if ra is not None:
            cooldown = max(cooldown, ra)  # אל תקטין אם Retry-After גדול יותר
    cooldown = min(cooldown, _max_cooldown_sec)
    _last_rest_ban_until_ts = _now() + cooldown
    logging.warning(f"[ws_fallback] REST cooldown engaged for {cooldown}s due to ban/rate-limit")

def _rest_allowed() -> bool:
    return _now() >= _last_rest_ban_until_ts

def _rest_status_is_ban(code: int) -> bool:
    # 403/418/429/503 = WAF/ban/ratelimit/temporarily unavailable
    return code in (403, 418, 429, 503)

# ===================== WS Manager =====================
class BinanceWSManager:
    def __init__(self, symbols: List[str]):
        self.symbols = _norm_symbols(symbols)
        self.ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._session: Optional[aiohttp.ClientSession] = None
        self.prices: Dict[str, float] = {}
        self.ts: Dict[str, float] = {}
        self.connected: bool = False
        self._lock = asyncio.Lock()
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()
        self._reconnect_needed = asyncio.Event()

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            # trust_env=False כדי לא למשוך פרוקסי לא רצוי; אם צריך פרוקסי, הפוך ל-True
            self._session = aiohttp.ClientSession(headers=_UA, trust_env=False)
        return self._session

    def _streams_url(self) -> Optional[str]:
        if not self.symbols:
            return None
        # bookTicker נותן bid/ask בזמן אמת; נחשב mid עבור כניסות שמרניות
        streams = "/".join(f"{s}@bookTicker" for s in self.symbols)
        return BINANCE_WS_URL_PREFIX + streams

    async def set_symbols(self, symbols: Iterable[str], replace: bool = True):
        """
        מחליף/מעדכן את רשימת הסמלים ומבקש התחברות מחדש.
        """
        new_syms = _norm_symbols(symbols)
        async with self._lock:
            if replace:
                changed = new_syms != self.symbols
                self.symbols = new_syms
                if changed:
                    self.prices.clear()
                    self.ts.clear()
            else:
                merged = _norm_symbols([*self.symbols, *new_syms])
                changed = merged != self.symbols
                self.symbols = merged
            if changed:
                self._reconnect_needed.set()

    async def _run(self):
        backoff = 0.6
        while not self._stop.is_set():
            url = self._streams_url()
            if not url:
                await asyncio.sleep(0.5)
                continue
            try:
                session = await self._ensure_session()
                # heartbeat/autoping כדי למנוע 1008
                async with session.ws_connect(
                    url, heartbeat=20, autoping=True, autoclose=True, timeout=20
                ) as ws:
                    async with self._lock:
                        self.ws = ws
                        self.connected = True
                    backoff = 0.6  # reset אחרי חיבור מוצלח
                    logging.info(f"[ws_fallback] WS connected for {len(self.symbols)} symbols")
                    self._reconnect_needed.clear()

                    async for msg in ws:
                        if self._reconnect_needed.is_set():
                            logging.info("[ws_fallback] reconnect requested (symbols changed)")
                            break

                        if msg.type == aiohttp.WSMsgType.TEXT:
                            try:
                                data = json.loads(msg.data)
                                payload = data.get("data") or {}
                                symbol = str(payload.get("s") or "").upper()
                                ask = payload.get("a")
                                bid = payload.get("b")
                                price = None
                                if ask is not None and bid is not None:
                                    price = (float(ask) + float(bid)) / 2.0
                                elif ask is not None:
                                    price = float(ask)
                                elif bid is not None:
                                    price = float(bid)
                                if symbol and price is not None:
                                    async with self._lock:
                                        self.prices[symbol] = price
                                        self.ts[symbol] = time.time()
                            except Exception as e:
                                logging.debug(f"[ws_fallback] parse error: {e}")
                        elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                            logging.warning(f"[ws_fallback] WS closed/error: {getattr(msg,'data', msg.type)}")
                            break
                        # ping/pong מטופל ע"י autoping
            except Exception as e:
                async with self._lock:
                    self.connected = False
                d = min(10.0, backoff)
                logging.warning(f"[ws_fallback] WS connect/reconnect failed: {e} → sleep {d:.2f}s")
                await asyncio.sleep(d)
                backoff = min(10.0, backoff * 2.0)
                continue

            # יצאנו מה-loop של ה־ws (סגירה או reconnect) → ננסה שוב
            async with self._lock:
                self.connected = False
                self.ws = None
            await asyncio.sleep(0.5)

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
            self._task = None
        if self._session is not None and not self._session.closed:
            try:
                await self._session.close()
            except Exception:
                pass
        async with self._lock:
            self.connected = False
            self.ws = None

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


# --- סינגלטון מנהל WS ---
binance_ws_manager: Optional[BinanceWSManager] = None

async def launch_multi_websocket(symbols: List[str]):
    global binance_ws_manager
    if binance_ws_manager is None:
        binance_ws_manager = BinanceWSManager(symbols)
        binance_ws_manager.start()
    else:
        await binance_ws_manager.set_symbols(symbols, replace=True)

async def add_ws_symbols(symbols: List[str]):
    """
    הוספת סמלים לרשימה הקיימת (לא מחליף). גורם ל-reconnect נקי.
    """
    global binance_ws_manager
    if binance_ws_manager is None:
        await launch_multi_websocket(symbols)
    else:
        await binance_ws_manager.set_symbols(symbols, replace=False)

async def stop_websocket():
    global binance_ws_manager
    if binance_ws_manager is not None:
        await binance_ws_manager.stop()
        binance_ws_manager = None

async def get_price(symbol: str) -> Optional[float]:
    global binance_ws_manager
    if binance_ws_manager is None:
        logging.debug("[ws_fallback] get_price called before WS start")
        return None
    return await binance_ws_manager.get_price(symbol)

def is_price_fresh(symbol: str, max_age_sec: int = DEFAULT_MAX_AGE_SEC) -> bool:
    """
    גרסה סינכרונית עבור קוד שלא רץ ב־async: משתמשת בטיימסטמפ ששמרנו.
    """
    global binance_ws_manager
    if binance_ws_manager is None or not binance_ws_manager.ts:
        return False
    t = binance_ws_manager.ts.get(str(symbol).upper())
    if not t:
        return False
    return (time.time() - t) <= max_age_sec

# -------------------------------------------------------
# REST Fallbacks — מודעות-באן (418/429) + backoff זהיר
# -------------------------------------------------------
def _handle_rest_response_for_ban(resp: requests.Response) -> bool:
    """בודק אם זו תשובת BAN/RateLimit ומפעיל cooldown; מחזיר True אם יש באן."""
    if _rest_status_is_ban(resp.status_code):
        _note_rest_ban(resp)
        return True
    return False

def _rest_futures_price(symbol: str, timeout: float = 5.0, retries: int = 3, backoff: float = 0.6) -> Optional[float]:
    if not _rest_allowed():
        logging.info("[ws_fallback] REST price skipped due to active cooldown")
        return None

    url = f"{FAPI_HTTP}/fapi/v1/ticker/price"
    params = {"symbol": symbol.upper()}
    last = None
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, params=params, timeout=timeout, headers=_UA)
            if r.status_code == 200:
                j = r.json()
                return float(j["price"])
            if _handle_rest_response_for_ban(r):
                # אל תנסה עוד — חזור מיד
                return None
            if r.status_code in (500, 502, 503, 504):
                d = min(10.0, backoff * (2 ** attempt))
                logging.warning(f"[ws_fallback] REST price {symbol} http={r.status_code} → sleep {d:.2f}s")
                time.sleep(d); last = r.text; continue
            r.raise_for_status()
        except Exception as e:
            d = min(10.0, backoff * (2 ** attempt))
            logging.warning(f"[ws_fallback] REST price network err (attempt {attempt+1}/{retries+1}) {symbol}: {e} → {d:.2f}s")
            time.sleep(d); last = e
    if last:
        logging.error(f"[ws_fallback] REST price failed for {symbol}: {last}")
    return None

async def get_price_smart(symbol: str, max_age_sec: int = DEFAULT_MAX_AGE_SEC) -> Optional[float]:
    """
    מחזיר מחיר WS אם טרי; אחרת ינסה REST (אם אין cooldown/ban פעיל).
    בזמן באן (418/429/403/503) הפונקציה תחזיר None במקום להחמיר את המצב.
    """
    p = await get_price(symbol)
    if p is not None and is_price_fresh(symbol, max_age_sec=max_age_sec):
        return p
    # fallback ל-REST (אם מותר כרגע)
    return _rest_futures_price(symbol)

# ---------- REST snapshot (סינכרוני) ל-klines עבור גיבוי מהיר ----------
def _rest_klines(
    market: str, symbol: str, interval: str, limit: int = 120,
    start_time: Optional[int] = None, end_time: Optional[int] = None,
    timeout: float = 10.0, retries: int = 3, backoff: float = 0.6
):
    if not _rest_allowed():
        logging.info("[ws_fallback] REST klines skipped due to active cooldown")
        return None

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
            if _handle_rest_response_for_ban(r):
                return None
            if r.status_code in (500, 502, 503, 504):
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
    בזמן באן פעיל יחזיר DataFrame ריק כדי לא לייצר עוד נסיונות REST.
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














