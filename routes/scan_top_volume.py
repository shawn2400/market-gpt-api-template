from __future__ import annotations
import asyncio
import os
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
import requests
from fastapi import APIRouter, Query

FUTURES_BASE = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com")
SPOT_BASE    = os.getenv("BINANCE_SPOT_HTTP_BASE",    "https://api.binance.com")

_S = requests.Session()
_S.trust_env = False
_S.headers.update({
    "User-Agent": "AlgoGPT/2 scan-topvol",
    "Accept": "application/json",
    "Accept-Encoding": "gzip",
})

router = APIRouter(prefix="/scan", tags=["Scan"])

def _get_top_symbols(market: str, quote: str, limit: int) -> List[str]:
    try:
        from utils.top_volume import get_top_volume_symbols
        ok, symbols = get_top_volume_symbols(market=market, quote=quote, limit=limit)
        if ok and symbols:
            return symbols
    except Exception:
        pass

    url = f"{FUTURES_BASE}/fapi/v1/ticker/24hr" if market == "futures" else f"{SPOT_BASE}/api/v3/ticker/24hr"
    try:
        r = _S.get(url, timeout=8)
        r.raise_for_status()
        items = r.json()
        rows: List[tuple[str, float]] = []
        for it in items:
            sym = str(it.get("symbol") or "").upper()
            if not sym.endswith(quote.upper()):
                continue
            try:
                qv = float(it.get("quoteVolume") or 0.0)
            except Exception:
                qv = 0.0
            rows.append((sym, qv))
        rows.sort(key=lambda t: t[1], reverse=True)
        return [s for s, _ in rows[: max(1, int(limit))]]
    except Exception:
        return []

def _klines(symbol: str, interval: str, limit: int, market: str) -> Optional[pd.DataFrame]:
    try:
        base = FUTURES_BASE if market == "futures" else SPOT_BASE
        path = "fapi/v1/klines" if market == "futures" else "api/v3/klines"
        url = f"{base}/{path}"
        r = _S.get(url, params={"symbol": symbol, "interval": interval, "limit": int(limit)}, timeout=8)
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







