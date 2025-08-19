# routes/multi_scan.py
from __future__ import annotations
from typing import List, Dict, Any, Optional, Literal
from datetime import datetime, timezone
import asyncio

from fastapi import APIRouter, Depends, Query, HTTPException, status

# ---- Auth ----
try:
    from utils.auth import require_bearer_token as _raw_require_bearer  # type: ignore

    def require_bearer_token():
        try:
            return _raw_require_bearer()
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=401, detail="Unauthorized")
except Exception:
    def require_bearer_token():
        return None

router = APIRouter(prefix="/scan", tags=["Scan"], dependencies=[Depends(require_bearer_token)])

# ---- Config helpers ----
def _cfg(name: str, default: Any) -> Any:
    try:
        from utils import config  # type: ignore
        return getattr(config, name, default)
    except Exception:
        return default

# ---- Executor status (אם קיים) ----
def _is_executor_running() -> bool:
    try:
        from utils.auto_executor import is_executor_running  # type: ignore
        return bool(is_executor_running())
    except Exception:
        return False

# ---- Single-symbol analyzer (בטוח) ----
async def _analyze_one(symbol: str, interval: str, market: str, bars: int = 200) -> Dict[str, Any]:
    sym = symbol.upper().strip()
    try:
        from utils.multi_tf_scanner import analyze_symbol  # type: ignore
        res = await analyze_symbol(symbol=sym, interval=interval, market_type=market, bars=bars)
        return {
            "symbol": sym,
            "market": market,
            "interval": interval,
            "frames": [interval],
            "trend": (res or {}).get("trend"),
            "direction": (res or {}).get("direction"),
            "rsi": (res or {}).get("rsi"),
            "adx": (res or {}).get("adx"),
            "volume": (res or {}).get("volume"),
            "quality_score": (res or {}).get("quality_score"),
            "signal": (res or {}).get("signal"),
            "confidence": (res or {}).get("confidence"),
            "reason": (res or {}).get("reason"),
            "close": (res or {}).get("close"),
            "atr": (res or {}).get("atr"),
        }
    except Exception as e:
        return {
            "symbol": sym,
            "market": market,
            "interval": interval,
            "frames": [interval],
            "trend": None,
            "direction": None,
            "rsi": None,
            "adx": None,
            "volume": None,
            "quality_score": None,
            "signal": None,
            "confidence": None,
            "reason": f"analyze-fallback: {type(e).__name__}",
            "close": None,
            "atr": None,
        }

# ---- /scan/info ----
@router.get("/info", operation_id="getScanInfo")
def get_scan_info():
    now = datetime.now(tz=timezone.utc).isoformat()
    notes: List[str] = []
    if _is_executor_running():
        notes.append("auto-executor running")
    else:
        notes.append("auto-executor not running")

    cfg = {
        "AUTO_RUN": bool(_cfg("AUTO_RUN", False)),
        "SCAN_INTERVAL": int(_cfg("SCAN_INTERVAL", 60)),
        "MIN_QUALITY_SCORE": float(_cfg("MIN_QUALITY_SCORE", 6)),
        "DEFAULT_INTERVAL": str(_cfg("DEFAULT_INTERVAL", "15m")),
        "TRENDING_ONLY": bool(_cfg("TRENDING_ONLY", False)),
    }
    return {
        "ok": True,
        "now_utc": now,
        "executor_running": _is_executor_running(),
        "config": cfg,
        "notes": notes,
    }

# ---- /scan  (סריקה מרובה) ----
@router.get("", operation_id="getScan")
async def get_scan(
    symbols: Optional[str] = Query(None, description="CSV e.g. BTCUSDT,ETHUSDT (אופציונלי)"),
    market_type: Literal["futures", "spot"] = Query("futures"),
    interval: str = Query(default=str(_cfg("DEFAULT_INTERVAL", "15m"))),
    top: int = Query(10, ge=1, le=50),
    min_quality: float = Query(default=float(_cfg("MIN_QUALITY_SCORE", 6.0))),
    trending_only: bool = Query(default=bool(_cfg("TRENDING_ONLY", False))),
    concurrency: int = Query(16, ge=2, le=64),
):
    """
    אם הועברו symbols → ננתח אותם אחד-אחד.
    אחרת ננסה multi_tf_scan_with_ai; אם לא קיים, ניקח top-volume כסורס לסימבולים.
    """
    # parse symbols
    symbols_list: List[str] = []
    if symbols:
        symbols_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]

    items: List[Dict[str, Any]] = []
    errors: List[str] = []

    # path A: explicit symbols
    if symbols_list:
        sem = asyncio.Semaphore(concurrency)

        async def _work(sym: str):
            async with sem:
                return await _analyze_one(sym, interval, market_type)

        results = await asyncio.gather(*(asyncio.create_task(_work(s)) for s in symbols_list), return_exceptions=True)
        for it in results:
            if isinstance(it, Exception):
                errors.append(f"{type(it).__name__}: {it}")
            else:
                items.append(it)
        return {"ok": True, "count": len(items), "items": items, "errors": errors or None}

    # path B: try multi_tf scanner
    try:
        from utils.multi_tf_scanner import multi_tf_scan_with_ai  # type: ignore

        res = await multi_tf_scan_with_ai(
            timeframes=(interval, "1h"),
            markets=(market_type,),
            min_quality=min_quality,
            top=top,
            trending_only=trending_only,
            trending_source="binance24h",
        )
        # נבטיח פורמט אחיד
        for r in res or []:
            items.append({
                "symbol": r.get("symbol"),
                "market": market_type,
                "interval": interval,
                "frames": [interval, "1h"],
                "trend": r.get("trend"),
                "direction": r.get("direction") or r.get("signal"),
                "rsi": r.get("rsi"),
                "adx": r.get("adx"),
                "volume": r.get("volume"),
                "quality_score": r.get("quality_score"),
                "signal": r.get("signal"),
                "confidence": r.get("confidence"),
                "reason": r.get("reason"),
                "close": r.get("close"),
                "atr": r.get("atr"),
            })
        return {"ok": True, "count": len(items), "items": items, "errors": None}
    except Exception as e:
        errors.append(f"scanner-missing: {type(e).__name__}")

    # path C: fallback via top-volume → then per-symbol analysis (lite)
    try:
        from utils.top_volume import get_top_volume_symbols  # type: ignore
        ok, syms = get_top_volume_symbols(market="futures" if market_type == "futures" else "spot", quote="USDT", limit=top)
        if not ok:
            raise RuntimeError("top-volume upstream failed")
        # analyze (lite) each symbol
        sem = asyncio.Semaphore(concurrency)
        async def _work(sym: str):
            async with sem:
                return await _analyze_one(sym, interval, market_type)
        results = await asyncio.gather(*(asyncio.create_task(_work(s)) for s in syms), return_exceptions=True)
        for it in results:
            if isinstance(it, Exception):
                errors.append(f"{type(it).__name__}: {it}")
            else:
                items.append(it)
        return {"ok": True, "count": len(items), "items": items, "errors": errors or None}
    except Exception as e:
        errors.append(f"fallback-failed: {type(e).__name__}")
        # אין מה לעשות יותר — תחזיר 503 ולא 500
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail={"ok": False, "errors": errors})























































