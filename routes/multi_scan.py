# routes/multi_scan.py
from __future__ import annotations
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, Query, Header, HTTPException, status
import concurrent.futures as cf
from datetime import datetime, timezone

import os

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

router = APIRouter(prefix="/scan", tags=["Scan"], dependencies=[Depends(require_bearer_token)])

def _get_cfg():
    try:
        from utils import config as cfg  # type: ignore
        return cfg
    except Exception:
        class _Dummy:
            AUTO_RUN = False
            ENABLE_AUTO_TRADING = False
            EXECUTE_TRADES = False
            SCAN_INTERVAL = 60
            MIN_QUALITY_SCORE = 6
            MAX_TRADE_BUDGET = 100.0
            TRENDING_ONLY = True
            DEFAULT_INTERVAL = "15m"
            SYMBOL_COOLDOWN_SEC = 600
            MAX_TRADES_PER_TICK = 3
        return _Dummy()  # type: ignore

def _is_executor_running_safe() -> Optional[bool]:
    try:
        from utils.auto_executor import is_executor_running  # type: ignore
        return bool(is_executor_running())
    except Exception:
        return None

def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()

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

@router.get("/info", summary="Scanner heartbeat / config / executor status", operation_id="getScanInfo")
def get_scan_info():
    cfg = _get_cfg()
    running = _is_executor_running_safe()
    notes = []
    if running is None:
        notes.append("auto_executor_unavailable")
    if not getattr(cfg, "ENABLE_AUTO_TRADING", False):
        notes.append("auto_trading_disabled")
    if getattr(cfg, "EXECUTE_TRADES", False) is False:
        notes.append("execute_trades_disabled")

    return {
        "ok": True,
        "now_utc": _iso_now(),
        "executor_running": running if running is not None else False,
        "config": {
            "AUTO_RUN": bool(getattr(cfg, "AUTO_RUN", False)),
            "ENABLE_AUTO_TRADING": bool(getattr(cfg, "ENABLE_AUTO_TRADING", False)),
            "EXECUTE_TRADES": bool(getattr(cfg, "EXECUTE_TRADES", False)),
            "SCAN_INTERVAL": int(getattr(cfg, "SCAN_INTERVAL", 60)),
            "MIN_QUALITY_SCORE": float(getattr(cfg, "MIN_QUALITY_SCORE", 6)),
            "MAX_TRADE_BUDGET": float(getattr(cfg, "MAX_TRADE_BUDGET", 100.0)),
            "TRENDING_ONLY": bool(getattr(cfg, "TRENDING_ONLY", True)),
            "DEFAULT_INTERVAL": str(getattr(cfg, "DEFAULT_INTERVAL", "15m")),
            "SYMBOL_COOLDOWN_SEC": int(getattr(cfg, "SYMBOL_COOLDOWN_SEC", 600)),
            "MAX_TRADES_PER_TICK": int(getattr(cfg, "MAX_TRADES_PER_TICK", 3)),
        },
        "notes": notes or None,
    }




















































