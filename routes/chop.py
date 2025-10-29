from __future__ import annotations
from typing import Any, Dict, List
from fastapi import APIRouter, Query, HTTPException
import pandas as pd
import httpx

from utils.chop_viewer import detect_chop_zones

router = APIRouter(prefix="/chop", tags=["Chop Zones"])

_BIN_FAPI = "https://fapi.binance.com/fapi/v1/klines"

_COLS = ["open_time","open","high","low","close","volume","close_time",
         "qv","nTrades","taker_base","taker_quote","x"]

def _to_df(rows: List[List[Any]]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=_COLS[:len(rows[0])] if rows and len(rows[0]) <= len(_COLS) else _COLS)
    # המספרים כ־float
    for c in ("open","high","low","close","volume"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df

@router.get("/{symbol}")
async def chop_zones(symbol: str, interval: str = Query("1h"), limit: int = Query(100)) -> List[Dict[str, Any]]:
    sym = symbol.upper()
    if not sym.endswith("USDT"):
        sym += "USDT"
    try:
        async with httpx.AsyncClient(timeout=10.0) as cli:
            r = await cli.get(_BIN_FAPI, params={"symbol": sym, "interval": interval, "limit": limit})
        if r.status_code != 200:
            raise HTTPException(status_code=502, detail=f"Binance error: {r.text[:160]}")
        raw = r.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"fetch failed: {e}")

    if not isinstance(raw, list) or not raw:
        return []

    df = _to_df(raw)
    df = detect_chop_zones(df)

    # נחזיר שדות יציבים בלבד
    out_cols = [c for c in ("open_time","close","adx","chop") if c in df.columns]
    return df[out_cols].tail(10).to_dict(orient="records")
