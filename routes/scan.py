# routes/scan.py
from __future__ import annotations
from fastapi import APIRouter, Query
from typing import Dict, Any, List
import os, requests, pandas as pd

from utils.indicators import prepare_indicators_for_backtest

FUTURES_BASE = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com")

router = APIRouter(prefix="/scan", tags=["Scan"])

def _fetch_klines(symbol: str, interval: str = "15m", limit: int = 200) -> pd.DataFrame:
    url = f"{FUTURES_BASE}/fapi/v1/klines"
    r = requests.get(url, params={"symbol": symbol, "interval": interval, "limit": int(limit)}, timeout=10)
    r.raise_for_status()
    arr = r.json()
    if not arr:
        return pd.DataFrame()
    cols = ["open_time","open","high","low","close","volume","close_time",
            "qv","nTrades","taker_base","taker_quote","x"]
    df = pd.DataFrame(arr, columns=cols[:len(arr[0])])
    for c in ("open","high","low","close","volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df[["open","high","low","close","volume"]]

@router.get("/info", summary="Basic Scan Info")
async def scan_info(symbol: str = Query(..., description="Symbol e.g. BTCUSDT"),
                    interval: str = Query("15m")) -> Dict[str, Any]:
    try:
        df = _fetch_klines(symbol, interval)
        if df.empty:
            return {"ok": False, "error": "no data"}
        ind = prepare_indicators_for_backtest(df)
        row = ind.iloc[-1].to_dict()
        return {"ok": True, "symbol": symbol, "interval": interval, "indicators": row}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@router.get("/", summary="Multi-symbol scan")
async def scan_symbols(symbols: List[str] = Query(..., description="List of symbols e.g. BTCUSDT,ETHUSDT"),
                       interval: str = Query("15m")) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for s in symbols:
        try:
            df = _fetch_klines(s, interval)
            if df.empty:
                out[s] = {"ok": False, "error": "no data"}
                continue
            ind = prepare_indicators_for_backtest(df)
            row = ind.iloc[-1].to_dict()
            out[s] = {"ok": True, "indicators": row}
        except Exception as e:
            out[s] = {"ok": False, "error": str(e)}
    return {"ok": True, "results": out}







