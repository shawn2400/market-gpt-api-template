# routes/context.py
from __future__ import annotations
from fastapi import APIRouter, Query, Body
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import pandas as pd
import requests
import os

from utils.indicators import prepare_indicators_for_backtest

FUTURES_BASE = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com")
context_router = APIRouter()

def _fetch_klines(symbol: str, interval: str = "15m", limit: int = 200) -> pd.DataFrame:
    url = f"{FUTURES_BASE}/fapi/v1/klines"
    r = requests.get(url, params={"symbol": symbol.upper(), "interval": interval, "limit": int(limit)}, timeout=10)
    r.raise_for_status()
    arr = r.json()
    if not arr:
        return pd.DataFrame()
    cols = ["open_time","open","high","low","close","volume","close_time","qv","nTrades","taker_base","taker_quote","x"]
    df = pd.DataFrame(arr, columns=cols[:len(arr[0])])
    for c in ("open","high","low","close","volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df

def _vol_regime_pct(df: pd.DataFrame) -> str:
    try:
        atr = float(df["atr"].iloc[-1]); price = float(df["close"].iloc[-1])
        pct = (atr/price)*100.0 if price>0 else 0.0
        if pct < 1.2: return "low"
        if pct < 2.5: return "mid"
        return "high"
    except Exception:
        return "mid"

def _danger_chop_flag(df: pd.DataFrame) -> bool:
    try:
        adx = float(df["adx"].iloc[-1])
        mid = float(df["bb_mid"].iloc[-1]); up = float(df["bb_upper"].iloc[-1]); lo = float(df["bb_lower"].iloc[-1])
        price = float(df["close"].iloc[-1])
        width = ((up-lo)/mid) if mid>0 else 0.0
        near_mid = abs(price-mid)/mid if mid>0 else 0.0
        return (adx < 18) and (width < 0.025) and (near_mid < 0.005)
    except Exception:
        return False

class CtxOut(BaseModel):
    symbol: str
    price: float | None = None
    ind: Dict[str, float | None] = {}
    filters: Dict[str, Any] = {}

@context_router.get("/", response_model=CtxOut)
def context_single(symbol: str = Query(...), interval: str = Query("15m"), compact: bool = Query(True)) -> CtxOut:
    df = _fetch_klines(symbol, interval=interval, limit=200)
    if df.empty:
        return CtxOut(symbol=symbol.upper(), price=None, ind={}, filters={})
    base = prepare_indicators_for_backtest(df)
    row = base.iloc[-1]
    price = float(row["close"])
    ind = {
        "rsi": float(row["rsi"]), "adx": float(row["adx"]), "atr": float(row["atr"]),
        "ema_21": float(row["ema_21"]), "bb_mid": float(row["bb_mid"]),
        "bb_upper": float(row["bb_upper"]), "bb_lower": float(row["bb_lower"]),
        "macd_hist": float(row["macd_hist"]),
    }
    flt = {"vol_regime": _vol_regime_pct(base), "danger_chop": _danger_chop_flag(base)}
    return CtxOut(symbol=symbol.upper(), price=price, ind=ind, filters=flt)

class CtxBatchIn(BaseModel):
    symbols: List[str]
    interval: str = "15m"
    compact: bool = True

class CtxBatchOut(BaseModel):
    ok: bool = True
    items: List[CtxOut]

@context_router.post("/batch", response_model=CtxBatchOut)
def context_batch(payload: CtxBatchIn = Body(...)) -> CtxBatchOut:
    items: List[CtxOut] = []
    syms = [s.strip().upper() for s in payload.symbols if s.strip()]
    for s in syms:
        try:
            it = context_single(symbol=s, interval=payload.interval, compact=payload.compact)
            items.append(it)
        except Exception:
            items.append(CtxOut(symbol=s, price=None, ind={}, filters={}))
    return CtxBatchOut(ok=True, items=items)



