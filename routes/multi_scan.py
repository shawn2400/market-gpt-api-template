# routes/multi_scan.py
from __future__ import annotations
from typing import List, Dict, Any
from fastapi import APIRouter, Depends, Query, Header, HTTPException, status
import concurrent.futures as cf
import os, time

# ---- Auth (Bearer) ----
try:
    from utils.auth import require_bearer_token  # type: ignore
except Exception:
    def require_bearer_token(authorization: str = Header(default="")):
        expected = (os.getenv("API_BEARER_TOKEN") or "").strip()
        if not expected:
            return None
        if not authorization.startswith("Bearer "):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
        got = authorization.split(" ", 1)[1].strip()
        if got != expected:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
        return None

# ---- Optional global scan state (אם יש לכם מנהל מצב פנימי, החלף בזה) ----
class _ScanState:
    running: bool = False
    last_run_ts: float | None = None
    symbols: list[str] = []
    errors: list[str] = []

scan_state = _ScanState()

def _safe_float(x, d: float = 0.0) -> float:
    try:
        v = float(x)
        return v if v == v else d
    except Exception:
        return d

try:
    from utils.top_volume import get_top_volume_symbols  # type: ignore
except Exception:
    try:
        from analytics.top_volume import get_top_volume_symbols  # type: ignore
    except Exception:
        get_top_volume_symbols = None  # type: ignore

def _scan_one(symbol: str, timeframe: str, bars: int, ind_kwargs: Dict[str, Any]) -> Dict[str, Any]:
    out = {"symbol": symbol, "timeframe": timeframe, "side": None, "score": 0.0, "note": None, "details": None}
    try:
        df = None
        try:
            from utils.get_klines import get_klines  # type: ignore
            df = get_klines(symbol, timeframe=timeframe, limit=int(bars), futures=True)
        except Exception:
            pass
        if df is None or len(df) < 10:
            out["note"] = "no_klines"
            return out

        try:
            from utils.indicators_ext import add_extended_indicators, extended_score_last_row  # type: ignore
            dfi = add_extended_indicators(df, **ind_kwargs)
            row = dfi.iloc[-1]
            score, side, conf, reason = extended_score_last_row(row)
            out["score"] = float(score)
            out["side"] = side
            out["note"] = reason
            out["details"] = {
                "close": _safe_float(row.get("close")),
                "ema_fast": _safe_float(row.get("ema_fast")),
                "ema_slow": _safe_float(row.get("ema_slow")),
                "adx": _safe_float(row.get("adx")),
                "ich_state": str(row.get("ichimoku_state") or ""),
                "ms_trend": str(row.get("ms_trend") or ""),
                "trending": bool(row.get("trending")),
                "confidence": float(conf),
            }
            return out
        except Exception:
            out["note"] = "indicators_failed"
            return out
    except Exception:
        out["note"] = "scan_failed"
        return out

router = APIRouter(prefix="/scan", tags=["Scan"], dependencies=[Depends(require_bearer_token)])

@router.get("/info", summary="Scanner heartbeat/info", operation_id="getScanInfo")
def get_scan_info():
    return {
        "running": bool(scan_state.running),
        "last_run_ts": scan_state.last_run_ts,
        "last_run_ago_sec": (time.time() - scan_state.last_run_ts) if scan_state.last_run_ts else None,
        "symbols": scan_state.symbols,
        "last_errors": scan_state.errors,
    }

@router.get("/top-volume", summary="Scan top-volume symbols concurrently (extended)", operation_id="getScanTopVolume")
def get_scan_top_volume(
    market: str = Query("futures", enum=["futures", "spot"]),
    quote: str = Query("USDT"),
    limit: int = Query(50, ge=1, le=200),
    timeframe: str = Query("15m"),
    bars: int = Query(200, ge=50, le=1500),
    trending_only: bool = Query(False),
    min_adx: float = Query(20.0, ge=5.0, le=60.0),
    ema_fast: int = Query(21, ge=3, le=200),
    ema_slow: int = Query(50, ge=5, le=400),
    adx_len: int = Query(14, ge=5, le=50),
    st_period: int = Query(10, ge=5, le=50),
    st_factor: float = Query(3.0, ge=1.0, le=10.0),
    ich_conv: int = Query(9, ge=5, le=50),
    ich_base: int = Query(26, ge=10, le=100),
    ich_span_b: int = Query(52, ge=20, le=200),
    ms_lookback: int = Query(5, ge=2, le=20),
    ms_pivot_span: int = Query(3, ge=1, le=10),
    concurrency: int = Query(16, ge=2, le=64),
):
    # 1) רשימת סימבולים
    symbols: List[str] = []
    if get_top_volume_symbols is not None:
        try:
            ok, symbols = get_top_volume_symbols(market=market, quote=quote, limit=limit)
            if not ok:
                symbols = []
        except Exception:
            symbols = []
    if not symbols:
        return {"ok": True, "count": 0, "signals": []}

    ind_kwargs = dict(
        ema_fast=ema_fast, ema_slow=ema_slow,
        adx_len=adx_len, st_period=st_period, st_factor=st_factor,
        ichimoku_conv=ich_conv, ichimoku_base=ich_base, ichimoku_span_b=ich_span_b,
        ms_lookback=ms_lookback, ms_pivot_span=ms_pivot_span,
    )

    # 2) סריקה מקבילית
    scan_state.running = True
    scan_state.last_run_ts = time.time()
    scan_state.symbols = symbols
    scan_state.errors = []

    signals: List[Dict[str, Any]] = []
    try:
        with cf.ThreadPoolExecutor(max_workers=int(concurrency)) as pool:
            futs = [pool.submit(_scan_one, s, timeframe, bars, ind_kwargs) for s in symbols]
            for f in futs:
                try:
                    signals.append(f.result(timeout=60))
                except Exception as e:
                    scan_state.errors.append(str(e))
    finally:
        scan_state.running = False

    # 3) סינון
    if trending_only:
        signals = [x for x in signals if x.get("details") and bool(x["details"].get("trending"))]
    if min_adx is not None:
        signals = [x for x in signals if x.get("details") and _safe_float(x["details"].get("adx"), 0.0) >= float(min_adx)]

    return {"ok": True, "count": len(signals), "signals": signals}


















































