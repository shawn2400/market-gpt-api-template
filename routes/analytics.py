# routes/analytics.py
from __future__ import annotations
from typing import List, Dict, Any, Union
from fastapi import APIRouter, Depends, Query, Body, HTTPException

try:
    from utils.auth import require_bearer_token
except Exception:
    async def require_bearer_token(*_a, **_k):
        raise HTTPException(status_code=401, detail="Unauthorized")

try:
    from utils.correlation import correlate_to_btc
    from utils.macro import macro_snapshot
    from utils.sentiment import sentiment_summary
    from utils.time_to_target import eta_to_target
except ImportError as e:
    raise RuntimeError(f"Missing utils module for analytics: {e}")

# ✅ בלי prefix כאן (main.py כבר שם /analytics)
router = APIRouter(tags=["Analytics"], dependencies=[Depends(require_bearer_token)])


@router.get("/correlation", summary="Correlation ALT to BTC", operation_id="getCorrelation")
async def get_correlation(
    symbols: Union[str, List[str]] = Query(..., description="comma-separated or repeated symbols"),
    ref_symbol: str = Query("BTCUSDT"),
    timeframe: str = Query("15m"),
    window: int = Query(200, ge=50, le=2000),
) -> Dict[str, Any]:
    if isinstance(symbols, list):
        syms = symbols
    else:
        syms = [s for s in (symbols or "").replace(" ", "").split(",") if s]

    try:
        items = correlate_to_btc(syms, ref_symbol=ref_symbol, timeframe=timeframe, window=window)
        return {"ok": True, "items": items}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/macro", summary="Macro snapshot (DXY/NDX/SPX/FG/BTC.D)", operation_id="getMacro")
async def get_macro() -> Dict[str, Any]:
    try:
        return {"ok": True, "data": macro_snapshot()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/sentiment/summary", summary="Sentiment summary (-100..100)", operation_id="getSentiment")
async def get_sentiment() -> Dict[str, Any]:
    try:
        return {"ok": True, "data": sentiment_summary()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/eta/time-to-target", summary="ETA to TP/SL by ATR speed", operation_id="postEtaToTarget")
async def post_eta(req: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    try:
        return {"ok": True, "data": eta_to_target(
            entry=float(req["entry"]),
            tp=float(req["tp"]),
            sl=float(req["sl"]),
            atr=float(req["atr"]),
            timeframe=str(req["timeframe"]),
        )}
    except Exception as e:
        return {"ok": False, "error": str(e)}






































