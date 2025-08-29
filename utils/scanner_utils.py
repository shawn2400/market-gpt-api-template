# utils/scanner_utils.py
from __future__ import annotations

import asyncio
import os
import random
from typing import Any, Dict, List, Optional

import httpx
import pandas as pd
from ta.momentum import RSIIndicator
from ta.trend import ADXIndicator, EMAIndicator
from ta.volatility import AverageTrueRange

BINANCE_FAPI = os.getenv("BINANCE_FAPI", "https://fapi.binance.com")

# ניהול עומסים ורשת
_RETRY_STATUSES = {418, 429, 500, 502, 503, 504}
_MAX_CONCURRENCY = int(os.getenv("HTTP_MAX_CONCURRENCY", "8"))
_SEM = asyncio.Semaphore(_MAX_CONCURRENCY)

_HDRS = {
    "User-Agent": "AlgoGPT/2 scanner",
    "Accept": "application/json",
    "Accept-Encoding": "gzip",
}

_CLIENT: Optional[httpx.AsyncClient] = None

async def _get_client() -> httpx.AsyncClient:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = httpx.AsyncClient(
            timeout=httpx.Timeout(8.0),
            headers=_HDRS,
            limits=httpx.Limits(max_keepalive_connections=32, max_connections=64),
            http2=False,  # Binance FAPI יציב ב-HTTP/1.1
        )
    return _CLIENT

async def _http_get_json(
    url: str,
    params: Dict[str, Any] | None = None,
    tries: int = 5,
    timeout: float = 8.0,
) -> Any:
    last_err: Optional[Exception] = None
    for attempt in range(tries):
        try:
            async with _SEM:
                client = await _get_client()
                r = await client.get(url, params=params, timeout=timeout)

            if r.status_code == 200:
                return r.json()

            # קצב/עומס: כבדו Retry-After ו-X-MBX-USED-WEIGHT-1M אם קיים
            if r.status_code in _RETRY_STATUSES:
                retry_after = r.headers.get("Retry-After")
                used_weight = r.headers.get("X-MBX-USED-WEIGHT-1M") or r.headers.get("X-MBX-USED-WEIGHT")
                base = 0.6 * (2 ** attempt) + random.uniform(0.0, 0.3)
                if retry_after:
                    delay = max(float(retry_after), base)
                elif used_weight:
                    try:
                        w = int(used_weight)
                        # אם קרובים לתקרה (1200) — נרווח עוד קצת
                        delay = base + (0.001 * max(0, w - 1000))
                    except Exception:
                        delay = base
                else:
                    delay = base
                await asyncio.sleep(min(10.0, delay))
                continue

            r.raise_for_status()

        except Exception as e:
            last_err = e
            delay = min(10.0, 0.6 * (2 ** attempt) + random.uniform(0.0, 0.3))
            await asyncio.sleep(delay)
            continue

    if last_err:
        raise last_err
    raise RuntimeError("binance http unknown error")

async def _fetch_klines(symbol: str, interval: str, limit: int = 200) -> List[list]:
    url = f"{BINANCE_FAPI}/fapi/v1/klines"
    return await _http_get_json(
        url, params={"symbol": symbol, "interval": interval, "limit": int(limit)}
    )

async def fetch_ohlcv(symbol: str, interval: str = "15m", limit: int = 150) -> pd.DataFrame:
    raw = await _fetch_klines(symbol.upper(), interval=interval, limit=max(50, int(limit)))
    if not raw or len(raw) < 10:
        return pd.DataFrame()
    cols = [
        "open_time","open","high","low","close","volume",
        "close_time","qav","trades","taker_base","taker_quote","ignore",
    ]
    df = pd.DataFrame(raw, columns=cols)[["open_time","open","high","low","close","volume"]].copy()
    for c in ("open","high","low","close","volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df.dropna(inplace=True)
    df.rename(columns={"open_time": "timestamp"}, inplace=True)
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df.set_index("timestamp", inplace=True)
    return df

def _clamp(v: float, lo: float, hi: float) -> float:
    try:
        v = float(v)
    except Exception:
        v = lo
    return max(lo, min(hi, v))

async def analyze_symbol(
    symbol: str,
    *,
    market_type: str = "futures",
    timeframe: Optional[str] = None,
    interval: Optional[str] = None,
    limit: int = 150,
    trending_only: bool = False,
    frames: Optional[List[str]] = None,
) -> Optional[Dict[str, Any]]:
    sym = str(symbol).upper().strip()
    tf = (timeframe or interval or "15m").strip()

    raw = await _fetch_klines(sym, interval=tf, limit=max(100, int(limit)))
    if not raw or len(raw) < 60:
        return None

    cols = [
        "open_time","open","high","low","close","volume",
        "close_time","qav","trades","taker_base","taker_quote","ignore",
    ]
    df = pd.DataFrame(raw, columns=cols)
    for c in ("open","high","low","close","volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df.dropna(inplace=True)

    close = df["close"]
    high = df["high"]
    low  = df["low"]
    vol  = df["volume"]

    rsi = RSIIndicator(close=close, window=14).rsi()
    adx = ADXIndicator(high=high, low=low, close=close, window=14).adx()
    ema21 = EMAIndicator(close=close, window=21).ema_indicator()
    ema50 = EMAIndicator(close=close, window=50).ema_indicator()
    atr14 = AverageTrueRange(high=high, low=low, close=close, window=14).average_true_range()

    last_close = float(close.iloc[-1])
    last_rsi   = float(rsi.iloc[-1])
    last_adx   = float(adx.iloc[-1])
    last_ema21 = float(ema21.iloc[-1])
    last_ema50 = float(ema50.iloc[-1])
    last_atr   = float(atr14.iloc[-1])
    last_vol   = float(vol.iloc[-1])

    trend = "UP" if last_ema21 > last_ema50 else "DOWN"
    direction = "LONG" if (trend == "UP" and last_rsi >= 52) else (
        "SHORT" if (trend == "DOWN" and last_rsi <= 48) else ("LONG" if last_close > last_ema50 else "SHORT")
    )

    signal = "HOLD"
    conf = 40
    if last_adx >= 20:
        if direction == "LONG" and last_rsi >= 55:
            signal, conf = "BUY", 65
        elif direction == "SHORT" and last_rsi <= 45:
            signal, conf = "SELL", 65

    align_bonus = 2.0 if (
        (direction == "LONG" and trend == "UP") or
        (direction == "SHORT" and trend == "DOWN")
    ) else 0.0
    q = (max(0.0, last_adx - 15.0) / 5.0) + (abs(last_rsi - 50.0) / 10.0) + align_bonus
    quality = float(_clamp(q, 0.0, 10.0))

    reason = f"trend={trend} rsi={last_rsi:.1f} adx={last_adx:.1f} ema21/50={last_ema21:.1f}/{last_ema50:.1f}"

    generic = {
        "symbol": sym,
        "timeframe": tf,
        "side": direction,
        "score": round(quality, 2),
        "note": reason,
        "details": {
            "market": market_type,
            "frames": [tf] if not frames else frames,
            "trend": trend,
            "rsi": round(last_rsi, 2),
            "adx": round(last_adx, 2),
            "volume": round(last_vol, 2),
            "quality_score": round(quality, 2),
            "signal": signal,
            "confidence": int(_clamp(conf + (quality * 3), 0, 100)),
            "reason": reason,
            "close": round(last_close, 6),
            "atr": round(last_atr, 6),
        },
    }

    extras = {
        "market": market_type,
        "interval": tf,
        "frames": [tf] if not frames else frames,
        "trend": trend,
        "direction": direction,
        "rsi": round(last_rsi, 2),
        "adx": round(last_adx, 2),
        "volume": round(last_vol, 2),
        "quality_score": round(quality, 2),
        "signal": signal,
        "confidence": int(_clamp(conf + (quality * 3), 0, 100)),
        "reason": reason,
        "close": round(last_close, 6),
        "atr": round(last_atr, 6),
    }

    out = {**generic, **extras}
    return out

async def scan_all(
    symbols: List[str],
    *,
    timeframe: str = "15m",
    limit: int = 150,
) -> List[Dict[str, Any]]:
    tasks = [analyze_symbol(s, timeframe=timeframe, limit=limit) for s in symbols if (s or "").strip()]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    out: List[Dict[str, Any]] = []
    for r in results:
        if isinstance(r, Exception) or r is None:
            continue
        out.append(r)
    return out



















































































