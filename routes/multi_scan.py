# routes/multi_scan.py
from __future__ import annotations
from typing import List, Dict, Any, Optional
import concurrent.futures as cf
import os
from fastapi import APIRouter, Depends, Query, Header, HTTPException, status

# --- Auth (Bearer) ---
try:
    from utils.auth import require_bearer_token  # type: ignore
except Exception:
    def require_bearer_token(authorization: str = Header(default="")):
        expected = (os.getenv("API_BEARER_TOKEN") or "").strip()
        if not expected:
            return None  # dev
        if not authorization.startswith("Bearer "):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
        if authorization.split(" ", 1)[1].strip() != expected:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
        return None

# --- Helpers ---
def _safe_float(x, d: float = 0.0) -> float:
    try:
        v = float(x)
        return v if v == v else d
    except Exception:
        return d

# Top-volume provider (utils/top_volume.py)
try:
    from utils.top_volume import get_top_volume_symbols  # type: ignore
except Exception:
    get_top_volume_symbols = None  # type: ignore

# OHLCV + indicators – נטען רק כשצריך
def _scan_one(symbol: str, timeframe: str, bars: int, ind_kwargs: Dict[str, Any], market: str) -> Dict[str, Any]:
    out = {"symbol": symbol, "timeframe": timeframe, "side": None, "score": 0.0, "note": None, "details": None}
    try:
        df = None
        try:
            # פונקציה סינכרונית – נקרא ב־thread
            from utils.get_klines import get_klines  # type: ignore
            df = get_klines(symbol, interval=timeframe, limit=int(bars), market_type=market)
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

@router.get("/info", summary="Scanner/Executor status", operation_id="getScanInfo")
def get_scan_info():
    now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
    # נסה לקרוא מצב ה־auto_executor והקונפיג – לא חובה
    auto_notes: List[str] = []
    try:
        from utils.auto_executor import is_executor_running  # type: ignore
        executor_running = bool(is_executor_running())
    except Exception:
        executor_running = False
        auto_notes.append("auto_executor_unavailable")

    cfg = {}
    try:
        from utils import config as _cfg  # type: ignore
        cfg = {
            "AUTO_RUN": bool(getattr(_cfg, "AUTO_RUN", False)),
            "ENABLE_AUTO_TRADING": bool(getattr(_cfg, "ENABLE_AUTO_TRADING", False)),
            "EXECUTE_TRADES": bool(getattr(_cfg, "EXECUTE_TRADES", False)),
            "SCAN_INTERVAL": int(getattr(_cfg, "SCAN_INTERVAL", 60)),
            "MIN_QUALITY_SCORE": float(getattr(_cfg, "MIN_QUALITY_SCORE", 6)),
            "MAX_TRADE_BUDGET": float(getattr(_cfg, "MAX_TRADE_BUDGET", 100)),
            "TRENDING_ONLY": bool(getattr(_cfg, "TRENDING_ONLY", False)),
            "DEFAULT_INTERVAL": str(getattr(_cfg, "DEFAULT_INTERVAL", "15m")),
            "SYMBOL_COOLDOWN_SEC": int(getattr(_cfg, "SYMBOL_COOLDOWN_SEC", 600)),
            "MAX_TRADES_PER_TICK": int(getattr(_cfg, "MAX_TRADES_PER_TICK", 3)),
        }
        if not cfg["ENABLE_AUTO_TRADING"]:
            auto_notes.append("auto_trading_disabled")
        if not cfg["EXECUTE_TRADES"]:
            auto_notes.append("execute_trades_disabled")
    except Exception:
        pass

    return {"ok": True, "now_utc": now, "executor_running": executor_running, "config": cfg, "notes": auto_notes}

@router.get("/top-volume", summary="Scan top-volume symbols concurrently (extended)", operation_id="getScanTopVolume")
def get_scan_top_volume(
    market: str = Query("futures", enum=["futures", "spot"]),
    quote: str = Query("USDT"),
    limit: int = Query(30, ge=1, le=200),
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
    # (1) סמלים לפי נפח
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
        ema_fast=ema_fast, ema_slow=ema_slow, adx_len=adx_len,
        st_period=st_period, st_factor=st_factor,
        ichimoku_conv=ich_conv, ichimoku_base=ich_base, ichimoku_span_b=ich_span_b,
        ms_lookback=ms_lookback, ms_pivot_span=ms_pivot_span,
    )

    # (2) סריקה במקביל
    signals: List[Dict[str, Any]] = []
    with cf.ThreadPoolExecutor(max_workers=int(concurrency)) as pool:
        futures = [pool.submit(_scan_one, s, timeframe, bars, ind_kwargs, market) for s in symbols]
        for f in futures:
            try:
                signals.append(f.result(timeout=60))
            except Exception:
                pass

    # (3) סינונים לפי טרנד/ADX
    if trending_only:
        signals = [x for x in signals if x.get("details") and bool(x["details"].get("trending"))]
    if min_adx is not None:
        signals = [x for x in signals if x.get("details") and _safe_float(x["details"].get("adx"), 0.0) >= float(min_adx)]

    return {"ok": True, "count": len(signals), "signals": signals}





















































