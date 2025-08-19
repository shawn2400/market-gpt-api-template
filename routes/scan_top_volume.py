from __future__ import annotations
import asyncio
import os
import time
import json
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import requests
from fastapi import APIRouter, Query, HTTPException

# ==== Binance bases & rotation ====
FUT_PRIMARY = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com").rstrip("/")
SPOT_BASE   = os.getenv("BINANCE_SPOT_HTTP_BASE",    "https://api.binance.com").rstrip("/")
FAPI_POOL   = [
    FUT_PRIMARY,
    "https://fapi1.binance.com",
    "https://fapi2.binance.com",
    "https://fapi3.binance.com",
]

DEFAULT_TIMEOUT = float(os.getenv("BINANCE_HTTP_TIMEOUT_SEC", "6.0"))
TOP24_TTL_SEC   = int(os.getenv("TOP_VOLUME_TTL_SEC", "60"))  # הורדת משקל REST
VALID_QUOTES    = {q.strip().upper() for q in (os.getenv("VALID_QUOTES", "USDT,USDC,FDUSD,BUSD").split(",")) if q.strip()}

# ==== Shared HTTP session ====
_S = requests.Session()
_S.trust_env = False
_S.headers.update({
    "User-Agent": "Mozilla/5.0 (AlgoGPT scan-topvol)",
    "Accept": "application/json, text/plain, */*",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
})

router = APIRouter(prefix="/scan", tags=["Scan"])
router_symbols = APIRouter(prefix="/symbols", tags=["Analytics"])

# ==== ban/WAF detection & cache ====
_BAN_UNTIL_MS = 0
def _banned_now() -> bool:
    return int(time.time() * 1000) < _BAN_UNTIL_MS

def _is_cloudfront_html(resp: requests.Response) -> bool:
    ct = resp.headers.get("Content-Type", "")
    return (resp.status_code in (403, 502, 503)) and ("text/html" in ct.lower())

def _parse_maybe_binance_error(resp: requests.Response) -> Optional[Dict[str, Any]]:
    try:
        return resp.json()
    except Exception:
        return None

# קאש מינימלי ל־24hr (מפחית weight)
_TOP24_CACHE: Dict[str, Any] = {"ts": 0, "market": "", "items": None}

# ==== Helpers ====
def _http_get_json_rotating(path: str, params: Optional[Dict[str, Any]], label: str) -> Tuple[Any, str]:
    """GET JSON עם רוטציית דומיינים (Futures). מחזיר (json, base_used). זורק על כשל."""
    global _BAN_UNTIL_MS
    if _banned_now():
        raise RuntimeError("REST temporarily disabled: IP banned (-1003)")

    last_err: Optional[Exception] = None
    for idx, base in enumerate(FAPI_POOL):
        url = f"{base}{path}"
        try:
            r = _S.get(url, params=params, timeout=DEFAULT_TIMEOUT)
            if _is_cloudfront_html(r):
                last_err = RuntimeError(f"CloudFront blocked ({r.status_code}) {url}")
                time.sleep(0.25 * (idx + 1))
                continue
            if r.status_code != 200:
                j = _parse_maybe_binance_error(r)
                if isinstance(j, dict) and j.get("code") == -1003:
                    # ip banned / rate weight
                    _BAN_UNTIL_MS = int(time.time() * 1000) + 15 * 60 * 1000
                    last_err = RuntimeError("REST banned (-1003)")
                    time.sleep(0.25 * (idx + 1))
                    continue
                r.raise_for_status()
            # force json
            try:
                data = r.json()
            except Exception as je:
                raise RuntimeError(f"Non-JSON from {url}") from je
            return data, base
        except Exception as e:
            last_err = e
            time.sleep(0.25 * (idx + 1))
            continue
    if last_err:
        raise last_err
    raise RuntimeError(f"{label} failed (no domains reachable)")

def _get_top24_all(market: str) -> List[Dict[str, Any]]:
    """מביא את כל 24hr tickers (עם קאש)."""
    now = int(time.time())
    if _TOP24_CACHE["items"] and _TOP24_CACHE["market"] == market and (now - _TOP24_CACHE["ts"] < TOP24_TTL_SEC):
        return _TOP24_CACHE["items"]  # type: ignore[return-value]

    if market == "futures":
        data, used = _http_get_json_rotating("/fapi/v1/ticker/24hr", None, "24hr")
    else:
        # Spot אין רוטציה, זה בסיס יחיד
        url = f"{SPOT_BASE}/api/v3/ticker/24hr"
        r = _S.get(url, timeout=DEFAULT_TIMEOUT)
        if _is_cloudfront_html(r):
            raise RuntimeError(f"CloudFront blocked (spot) {url}")
        r.raise_for_status()
        data = r.json()

    if not isinstance(data, list):
        raise RuntimeError("24hr returned non-list payload")
    _TOP24_CACHE.update({"ts": now, "market": market, "items": data})
    return data

def _get_top_symbols(market: str, quote: str, limit: int, min_qv: float = 0.0) -> List[str]:
    try:
        # קאש פנימי שלך (אם קיים) — קודם כל
        from utils.top_volume import get_top_volume_symbols
        ok, symbols = get_top_volume_symbols(market=market, quote=quote, limit=limit, min_quote_volume=min_qv)
        if ok and symbols:
            return symbols
    except Exception:
        pass

    try:
        items = _get_top24_all(market)
        rows: List[Tuple[str, float]] = []
        q = quote.upper()
        for it in items:
            sym = str(it.get("symbol") or "").upper()
            if not sym.endswith(q):
                continue
            try:
                qv = float(it.get("quoteVolume") or 0.0)
            except Exception:
                qv = 0.0
            if qv < float(min_qv or 0.0):
                continue
            rows.append((sym, qv))
        rows.sort(key=lambda t: t[1], reverse=True)
        return [s for s, _ in rows[: max(1, int(limit))]]
    except Exception:
        return []

def _klines(symbol: str, interval: str, limit: int, market: str) -> Optional[pd.DataFrame]:
    """מביא קווים (REST) עם רוטציה + המרה ל-DataFrame. מחזיר None אם כשל."""
    try:
        if market == "futures":
            data, _ = _http_get_json_rotating("/fapi/v1/klines", {"symbol": symbol, "interval": interval, "limit": int(limit)}, "klines")
        else:
            url = f"{SPOT_BASE}/api/v3/klines"
            r = _S.get(url, params={"symbol": symbol, "interval": interval, "limit": int(limit)}, timeout=DEFAULT_TIMEOUT)
            if _is_cloudfront_html(r):
                return None
            if r.status_code != 200:
                return None
            data = r.json()

        if not data:
            return None
        df = pd.DataFrame(
            data,
            columns=[
                "openTime","open","high","low","close","volume",
                "closeTime","qv","nTrades","takerBase","takerQuote","x"
            ],
        )
        for c in ("open","high","low","close","volume"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df.dropna(subset=["open","high","low","close"], inplace=True)
        df["timestamp"] = pd.to_datetime(df["openTime"], unit="ms", utc=True)
        return df[["timestamp","open","high","low","close","volume"]]
    except Exception:
        return None

# ==== indicators / scoring ====
from utils.indicators_ext import add_extended_indicators, extended_score_last_row

@router.get("", summary="Scan root", operation_id="getScanRoot")
async def scan_root():
    return {"ok": True, "endpoints": ["/scan/info", "/scan/top-volume"]}

@router_symbols.get("/top-volume", operation_id="getTopVolumeSymbols", summary="Top symbols by 24h quote volume (Binance)")
async def symbols_top_volume(
    market: str = Query("futures", pattern="^(futures|spot)$"),
    quote: str = Query("USDT"),
    limit: int = Query(50, ge=1, le=200),
    min_quote_volume: float = Query(0.0, ge=0.0),
) -> Dict[str, Any]:
    if _banned_now():
        # החזר “ירוק” עם רשימה ריקה במקום 500
        return {"ok": True, "market": market, "quote": quote.upper(), "limit": limit, "symbols": []}
    try:
        syms = _get_top_symbols(market, quote, limit, min_quote_volume)
        return {"ok": True, "market": market, "quote": quote.upper(), "limit": limit, "symbols": syms}
    except Exception as e:
        raise HTTPException(status_code=503, detail={"code": "BINANCE_UNAVAILABLE", "error": str(e)})

@router.get("/top-volume", operation_id="getScanTopVolume", summary="Scan top-volume symbols concurrently (extended)")
async def scan_top_volume(
    market: str = Query("futures", pattern="^(futures|spot)$"),
    quote: str = Query("USDT"),
    limit: int = Query(50, ge=1, le=200),
    timeframe: str = Query("15m"),
    bars: int = Query(200, ge=50, le=1500),
    trending_only: bool = Query(False),
    min_adx: float = Query(20.0, ge=5.0, le=60.0),
    ema_fast: int = Query(21, ge=3, le=200),
    ema_slow: int = Query(50, ge=5, le=400),
    adx_len: int = Query(14, ge=5, le=50),
    concurrency: int = Query(16, ge=2, le=64),
) -> Dict[str, Any]:
    # ולידציה ל-quote
    q = quote.upper().strip()
    if q not in VALID_QUOTES:
        raise HTTPException(status_code=400, detail={"code": "BAD_QUOTE", "error": f"Invalid quote '{q}', allowed={sorted(VALID_QUOTES)}"})

    # אם כרגע יש באן — החזר 503 מפורש (לא 500)
    if _banned_now():
        raise HTTPException(status_code=503, detail={"code": "BINANCE_IP_BANNED", "error": "Temporarily banned (-1003). Use WS / retry later."})

    # קח symbols (עם קאש)
    symbols = _get_top_symbols(market, q, limit)
    if not symbols:
        return {"ok": True, "count": 0, "signals": [], "errors": [], "market": market, "quote": q}

    # ריסון קונקרנסי (הקטן אוטומטית אם יש עומס)
    eff_conc = min(concurrency, int(os.getenv("SCAN_EFFECTIVE_CONCURRENCY", "12")))
    sem = asyncio.Semaphore(eff_conc)

    results: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []

    async def _process(sym: str):
        async with sem:
            df = await asyncio.to_thread(_klines, sym, timeframe, bars, market)
            if df is None or df.empty:
                errors.append({"symbol": sym, "error": "klines_empty"})
                return
            df2 = add_extended_indicators(df, ema_fast=ema_fast, ema_slow=ema_slow, adx_len=adx_len)
            if df2.empty:
                errors.append({"symbol": sym, "error": "indicators_empty"})
                return
            row = df2.iloc[-1]
            score, side, conf, reason = extended_score_last_row(row)

            # ADX / trending פילטרים
            if min_adx and (float(row.get("adx", 0.0)) < float(min_adx)):
                return
            if trending_only and not bool(row.get("trending") is True):
                return

            results.append({
                "symbol": sym,
                "score": float(score),
                "side": side,
                "confidence": float(conf),
                "reason": reason,
                "adx": float(row.get("adx", 0.0)),
                "ema_fast": float(row.get("ema_fast", 0.0)),
                "ema_slow": float(row.get("ema_slow", 0.0)),
                "trending": bool(row.get("trending") is True),
            })

    await asyncio.gather(*[_process(s) for s in symbols])

    # מיין לפי score
    results.sort(key=lambda d: d["score"], reverse=True)

    return {
        "ok": True,
        "market": market,
        "quote": q,
        "limit": limit,
        "timeframe": timeframe,
        "bars": bars,
        "concurrency": eff_conc,
        "count": len(results),
        "signals": results,
        "errors": errors,  # שקוף – לא מפיל 500
    }











