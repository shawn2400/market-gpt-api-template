# routes/scan.py
from __future__ import annotations

from typing import List, Literal, Optional, Dict, Any, Iterable, Union
import asyncio
import inspect
import logging

from fastapi import APIRouter, Depends, HTTPException, Body, status

logger = logging.getLogger("algogpt.scan")
router = APIRouter(prefix="", tags=["Scan"])

# ---------------------------
# Auth (עם fallback בטוח ל-dev)
# ---------------------------
try:
    from utils.auth import require_bearer_token
except Exception as e:  # pragma: no cover
    logger.warning("Auth fallback active: %s", e)

    def require_bearer_token():
        # עבור GET /scan לא נשתמש בזה; רק ב-POSTים
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

# ---------------------------
# Utilities / Symbols
# ---------------------------
try:
    from utils.symbols import normalize_symbol
except Exception:
    def normalize_symbol(sym: str) -> str:  # type: ignore
        return (sym or "").upper().replace(" ", "").replace("-", "")

# ---------------------------
# Scanner functions
# ---------------------------
_analyze_symbol = None
_scan_all = None
try:
    from utils.scanner_utils import analyze_symbol as _analyze_symbol  # type: ignore
    from utils.scanner_utils import scan_all as _scan_all  # type: ignore
except Exception as e:
    logger.error("scanner_utils missing or invalid: %s", e)

# ---------------------------
# Models
# ---------------------------
Side = Literal["LONG", "SHORT"]

from pydantic import BaseModel, Field

class ScanSignal(BaseModel):
    symbol: str = Field(..., description="Trading symbol, e.g., BTCUSDT")
    timeframe: str = Field(..., description="e.g., 5m/15m/1h")
    side: Optional[Side] = Field(None, description="Suggested direction")
    score: float = Field(0.0, ge=0.0, le=10.0, description="Quality score 0–10")
    note: Optional[str] = Field(None, description="Short rationale / flags")
    details: Optional[Dict[str, Any]] = Field(default=None, description="Raw scanner details")

class ScanResponse(BaseModel):
    ok: bool
    count: int
    signals: List[ScanSignal] = Field(default_factory=list)

class SingleScanPayload(BaseModel):
    symbol: str = Field(..., examples=["BTCUSDT"])
    timeframe: str = Field("15m", examples=["5m", "15m", "1h"])
    limit: int = Field(200, ge=50, le=1500)

class MultiScanPayload(BaseModel):
    symbols: List[str] = Field(..., examples=[["BTCUSDT", "ETHUSDT"]])
    timeframe: str = Field("15m")
    limit: int = Field(200, ge=50, le=1500)

# ---------------------------
# Helpers
# ---------------------------
async def _maybe_await(func, *args, **kwargs):
    if inspect.iscoroutinefunction(func):
        return await func(*args, **kwargs)
    return func(*args, **kwargs)

def _ensure_scanner_available():
    if _analyze_symbol is None and _scan_all is None:
        raise HTTPException(
            status_code=500,
            detail="Scanner module not available (utils/scanner_utils.py)."
        )

def _normalize_symbols(symbols: Iterable[str]) -> List[str]:
    return [normalize_symbol(s) for s in symbols if (s or "").strip()]

# ---------------------------
# Routes
# ---------------------------

# פתוח ללא טוקן – heartbeat/info
@router.get("/scan", response_model=ScanResponse, summary="Basic scanner heartbeat (no auth)")
async def scan_info():
    """
    מידע בסיסי/בדיקת חיים לראוטר הסריקה (ללא צורך ב־Authorization).
    """
    _ensure_scanner_available()
    return ScanResponse(ok=True, count=0, signals=[])

# alias תואם ללקוחות ישנים (גם ללא אימות)
@router.get("/scan-info", response_model=ScanResponse, summary="Scanner heartbeat (alias)")
async def scan_info_alias():
    return await scan_info()

# מוגן בטוקן
@router.post(
    "/scan",
    response_model=ScanResponse,
    summary="Run single-symbol scan",
)
async def scan_single(
    payload: SingleScanPayload = Body(...),
    _=Depends(require_bearer_token),
):
    _ensure_scanner_available()

    symbol = normalize_symbol(payload.symbol)
    timeframe = payload.timeframe
    limit = payload.limit

    try:
        if _analyze_symbol is None:
            results = await _maybe_await(_scan_all, symbols=[symbol], timeframe=timeframe, limit=limit)  # type: ignore
            sigs = _convert_results(results)
        else:
            res = await _maybe_await(_analyze_symbol, symbol=symbol, interval=timeframe, limit=limit)  # type: ignore
            sigs = _convert_results([res] if res is not None else [])
        return ScanResponse(ok=True, count=len(sigs), signals=sigs)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("scan_single failed: %s", e)
        raise HTTPException(status_code=500, detail=f"scan_single error: {e}")

# מוגן בטוקן
@router.post(
    "/scan/multi",
    response_model=ScanResponse,
    summary="Run multi-symbol scan",
)
async def scan_multi(
    payload: MultiScanPayload = Body(...),
    _=Depends(require_bearer_token),
):
    _ensure_scanner_available()

    symbols = _normalize_symbols(payload.symbols)
    if not symbols:
        raise HTTPException(status_code=400, detail="symbols list is empty")

    timeframe = payload.timeframe
    limit = payload.limit

    try:
        if _scan_all is not None:
            results = await _maybe_await(_scan_all, symbols=symbols, timeframe=timeframe, limit=limit)  # type: ignore
            sigs = _convert_results(results)
        else:
            if _analyze_symbol is None:
                raise RuntimeError("No scanner functions available")
            tasks = [_maybe_await(_analyze_symbol, symbol=s, interval=timeframe, limit=limit) for s in symbols]  # type: ignore
            results = await asyncio.gather(*tasks, return_exceptions=True)
            clean: List[Any] = []
            for r in results:
                if isinstance(r, Exception):
                    logger.warning("scan_multi: symbol failed: %s", r)
                    continue
                clean.append(r)
            sigs = _convert_results(clean)

        return ScanResponse(ok=True, count=len(sigs), signals=sigs)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("scan_multi failed: %s", e)
        raise HTTPException(status_code=500, detail=f"scan_multi error: {e}")

# ---------------------------
# Result normalization
# ---------------------------
def _convert_results(results: Union[List[Any], Any]) -> List[ScanSignal]:
    out: List[ScanSignal] = []
    if results is None:
        return out
    if not isinstance(results, list):
        results = [results]

    for r in results:
        try:
            data: Dict[str, Any]
            if isinstance(r, dict):
                data = r
            else:
                data = {
                    "symbol": getattr(r, "symbol", None),
                    "timeframe": getattr(r, "interval", None) or getattr(r, "timeframe", None),
                    "side": getattr(r, "side", None),
                    "score": getattr(r, "quality_score", None) or getattr(r, "score", None),
                    "note": getattr(r, "reason", None) or getattr(r, "note", None),
                    "details": getattr(r, "details", None),
                }

            sym = normalize_symbol(str(data.get("symbol") or ""))
            tf = str(data.get("timeframe") or "15m")
            side = data.get("side")
            if side is not None:
                side = str(side).upper()
                if side not in ("LONG", "SHORT"):
                    side = None
            score = float(data.get("score") or 0.0)
            note = data.get("note")
            details = data.get("details")

            out.append(
                ScanSignal(
                    symbol=sym,
                    timeframe=tf,
                    side=side,  # type: ignore
                    score=max(0.0, min(10.0, score)),
                    note=note if (note is None or isinstance(note, str)) else str(note),
                    details=details if isinstance(details, dict) else (
                        {"raw": details} if details is not None else None
                    ),
                )
            )
        except Exception as e:
            logger.warning("Skipping bad scan result: %s (raw=%r)", e, r)
            continue
    return out

