# utils/scanner_utils.py
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

import httpx
import pandas as pd
from ta.momentum import RSIIndicator
from ta.trend import ADXIndicator, EMAIndicator
from ta.volatility import AverageTrueRange

BINANCE_FAPI = "https://fapi.binance.com"

_RETRY_STATUSES = {418, 429, 500, 502, 503, 504}
_HDRS = {
    "User-Agent": "AlgoGPT/2 scanner",
    "Accept": "application/json",
    "Accept-Encoding": "gzip",
}


async def _http_get_json(
    url: str,
    params: Dict[str, Any] | None = None,
    tries: int = 4,
    timeout: float = 8.0,
):
    last_err: Optional[Exception] = None
    for attempt in range(tries):
        try:
            async with httpx.AsyncClient(timeout=timeout, headers=_HDRS) as x:
                r = await x.get(url, params=params)
            if r.status_code == 200:
                return r.json()
            if r.status_code in _RETRY_STATUSES:
                delay = min(5.0, 0.6 * (2 ** attempt))
                await asyncio.sleep(delay)
                continue
            r.raise_for_status()
        except Exception as e:
            last_err = e
            delay = min(5.0, 0.6 * (2 ** attempt))
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
    """
    מחזיר DataFrame עם OHLCV מסודר על ציר זמן UTC מתוך Binance Futures klines.
    """
    raw = await _fetch_klines(symbol.upper(), interval=interval, limit=max(50, int(limit)))
    if not raw or len(raw) < 10:
        return pd.DataFrame()
    cols = [
        "open_time","open","high","low","close","volume",
        "close_time","qav","trades","taker_base","taker_quote","ignore",
    ]
    df = pd.DataFrame(raw, columns=cols)[
        ["open_time","open","high","low","close","volume"]
    ].copy()
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
    # תאימות: ניתן להעביר timeframe או interval
    timeframe: Optional[str] = None,
    interval: Optional[str] = None,
    limit: int = 150,
    trending_only: bool = False,  # שמור לעתיד
    frames: Optional[List[str]] = None,
) -> Optional[Dict[str, Any]]:
    """
    ניתוח סימבול ל-Binance Futures: RSI/ADX/EMA/ATR + ציון איכות 0–10.
    החזרה בפורמט שה-routers של /scan מצפים לו (timeframe/side/score/note/details).
    """
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

    # סיגנל/ביטחון בסיסיים
    signal = "HOLD"
    conf = 40
    if last_adx >= 20:
        if direction == "LONG" and last_rsi >= 55:
            signal, conf = "BUY", 65
        elif direction == "SHORT" and last_rsi <= 45:
            signal, conf = "SELL", 65

    # ציון איכות 0–10
    align_bonus = 2.0 if (
        (direction == "LONG" and trend == "UP") or
        (direction == "SHORT" and trend == "DOWN")
    ) else 0.0
    q = (max(0.0, last_adx - 15.0) / 5.0) + (abs(last_rsi - 50.0) / 10.0) + align_bonus
    quality = float(_clamp(q, 0.0, 10.0))

    reason = f"trend={trend} rsi={last_rsi:.1f} adx={last_adx:.1f} ema21/50={last_ema21:.1f}/{last_ema50:.1f}"

    # מבנה “גנרי” ל-/scan
    generic = {
        "symbol": sym,
        "timeframe": tf,                     # חשוב: scan.py מחפש timeframe
        "side": direction,                   # כיוון מוצע
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

    # שדות “מקוריים” לשימושים אחרים/תאימות
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
    """
    סריקה מרובת סימבולים; מחזיר רשימה בפורמט התואם ל-/scan.
    """
    tasks = [
        analyze_symbol(s, timeframe=timeframe, limit=limit)
        for s in symbols if (s or "").strip()
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    out: List[Dict[str, Any]] = []
    for r in results:
        if isinstance(r, Exception) or r is None:
            continue
        out.append(r)
    return out
















































































