# routes/executor.py
from __future__ import annotations

import time
from typing import List, Dict, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Path
from pydantic import BaseModel, Field, constr

from utils.auth import require_api_key
from utils.trade_manager import get_trade_history
from utils.binance_client import (
    fapi_ping,
    futures_open_positions,
    futures_balance,
    futures_mark_price,
    futures_exchange_info_safe,
    get_symbol_info,
)

router = APIRouter(
    prefix="/executor",
    tags=["Executor"],
    dependencies=[Depends(require_api_key)],
)

# =========
# MODELS
# =========
class PositionModel(BaseModel):
    symbol: str
    positionAmt: str
    entryPrice: str
    breakEvenPrice: str
    markPrice: str
    unRealizedProfit: str
    liquidationPrice: str
    leverage: str
    marginType: constr(strip_whitespace=True)  # "cross"/"isolated"
    positionSide: constr(strip_whitespace=True)  # "BOTH"/"LONG"/"SHORT"
    isolated: bool = False
    updateTime: int = 0

class BalanceModel(BaseModel):
    accountAlias: Optional[str] = None
    asset: str
    balance: str
    crossWalletBalance: Optional[str] = None
    crossUnPnl: Optional[str] = None
    availableBalance: Optional[str] = None
    maxWithdrawAmount: Optional[str] = None
    updateTime: Optional[int] = 0

class PositionsResponse(BaseModel):
    ok: bool = True
    total: int
    items: List[PositionModel] = Field(default_factory=list)

class BalancesResponse(BaseModel):
    ok: bool = True
    total: int
    items: List[BalanceModel] = Field(default_factory=list)

class SymbolsResponse(BaseModel):
    ok: bool = True
    total: int
    items: List[str] = Field(default_factory=list)

class SymbolInfoResponse(BaseModel):
    ok: bool = True
    symbol: str
    info: Dict[str, Any]

class MarkPriceResponse(BaseModel):
    ok: bool = True
    symbol: str
    mark_price: float

class ExchangeInfoResponse(BaseModel):
    ok: bool = True
    symbols_count: int
    raw: Dict[str, Any]

class StatusResponse(BaseModel):
    ok: bool = True
    executor: str = "running"
    endpoints: Dict[str, str] = Field(
        default_factory=lambda: {
            "ping": "/executor/ping",
            "positions": "/executor/positions",
            "balance": "/executor/balance",
            "symbols": "/executor/symbols",
            "symbol_info": "/executor/symbol-info/{symbol}",
            "mark_price": "/executor/mark-price/{symbol}",
            "exchange_info": "/executor/exchange-info",
            "trades": "/executor/trades",
            "health": "/executor/health",
            "status": "/executor/status",
        }
    )

class HealthResponse(BaseModel):
    ok: bool = True
    binance_ping: bool
    signed_balance_ok: bool
    mark_price_ok: bool
    details: Dict[str, Any] = Field(default_factory=dict)
    cached: bool = False
    ttl_seconds: int = 10

# =========
# ENDPOINTS
# =========

@router.get("/ping", response_model=StatusResponse)
def ping() -> StatusResponse:
    """בדיקת זמינות Binance Futures API (פינג ציבורי)."""
    ok = bool(fapi_ping())
    if not ok:
        raise HTTPException(status_code=502, detail="Binance ping failed")
    return StatusResponse(ok=True)

@router.get("/positions", response_model=PositionsResponse)
def list_open_positions() -> PositionsResponse:
    """פוזיציות פתוחות (positionRisk)."""
    try:
        data = futures_open_positions() or []
        items = [PositionModel(**p) for p in data]
        return PositionsResponse(total=len(items), items=items)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch positions: {e}")

@router.get("/balance", response_model=BalancesResponse)
def list_balance() -> BalancesResponse:
    """מאזן Futures חתום (fapi/v2/balance)."""
    try:
        data = futures_balance() or []
        items = [BalanceModel(**b) for b in data]
        return BalancesResponse(total=len(items), items=items)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch balance: {e}")

@router.get("/symbols", response_model=SymbolsResponse)
def list_symbols(limit: int = Query(0, ge=0, le=5000)) -> SymbolsResponse:
    """רשימת סימבולים פעילים ב-Futures. אפשר להגביל עם limit."""
    try:
        info = futures_exchange_info_safe(force_refresh=False)
        symbols = [s["symbol"] for s in info.get("symbols", [])]
        if limit and limit > 0:
            symbols = symbols[:limit]
        return SymbolsResponse(total=len(symbols), items=symbols)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch symbols: {e}")

@router.get("/symbol-info/{symbol}", response_model=SymbolInfoResponse)
def symbol_info(symbol: str = Path(..., min_length=3, max_length=20)) -> SymbolInfoResponse:
    """exchangeInfo עבור סימבול ספציפי (כולל פילטרים)."""
    try:
        info = get_symbol_info(symbol, force_refresh=False)
        if not info:
            raise HTTPException(status_code=404, detail=f"Symbol {symbol.upper()} not found")
        return SymbolInfoResponse(symbol=symbol.upper(), info=info)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch symbol info: {e}")

@router.get("/mark-price/{symbol}", response_model=MarkPriceResponse)
def mark_price(symbol: str = Path(..., min_length=3, max_length=20)) -> MarkPriceResponse:
    """Mark Price עדכני לסימבול (עם fallback פנימי אם יש)."""
    try:
        mp = futures_mark_price(symbol)
        if mp is None:
            raise HTTPException(status_code=502, detail=f"Mark price not available for {symbol.upper()}")
        return MarkPriceResponse(symbol=symbol.upper(), mark_price=mp)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch mark price: {e}")

@router.get("/exchange-info", response_model=ExchangeInfoResponse)
def exchange_info(refresh: bool = Query(False, description="Force refresh from Binance")) -> ExchangeInfoResponse:
    """exchangeInfo מלא; ניתן לרענן בכפייה עם refresh=true."""
    try:
        info = futures_exchange_info_safe(force_refresh=bool(refresh))
        return ExchangeInfoResponse(symbols_count=len(info.get("symbols", [])), raw=info)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch exchange info: {e}")

@router.get("/trades", response_model=List[Dict[str, Any]])
def list_trades(limit: int = Query(50, ge=1, le=500)):
    """היסטוריית טריידים פנימית (מה-storage שלך)."""
    try:
        return get_trade_history(limit=limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch trades: {e}")

@router.get("/status", response_model=StatusResponse)
def executor_status() -> StatusResponse:
    """סטטוס Executor בסיסי (שרת רץ וקישורים)."""
    return StatusResponse(ok=True)

# =========
# HEALTH (קליל עם Cache)
# =========
_health_cache: Dict[str, Any] = {"ts": 0.0, "payload": None}
_HEALTH_TTL = 10  # שניות

@router.get("/health", response_model=HealthResponse)
def health_check(symbol: str = Query("BTCUSDT", min_length=3, max_length=20)) -> HealthResponse:
    """
    בדיקת בריאות קלת-משקל:
    - ping ציבורי ל-Binance Futures
    - קריאה חתומה קצרה (balance) לאימות מפתחות/הרשאות
    - Mark Price לסימבול (ברירת מחדל BTCUSDT)
    תוצאת הבדיקה נשמרת ל-10 שניות כדי למנוע עומס.
    """
    now = time.time()
    if _health_cache["payload"] and (now - _health_cache["ts"] < _HEALTH_TTL):
        cached_payload: Dict[str, Any] = dict(_health_cache["payload"])
        cached_payload["cached"] = True
        return HealthResponse(**cached_payload)

    details: Dict[str, Any] = {}

    # 1) Ping ציבורי
    try:
        ping_ok = bool(fapi_ping())
    except Exception as e:
        ping_ok = False
        details["ping_error"] = str(e)

    # 2) חתום: balance
    try:
        bal = futures_balance()
        signed_ok = isinstance(bal, list)
        if not signed_ok:
            details["balance_raw"] = bal
    except Exception as e:
        signed_ok = False
        details["balance_error"] = str(e)

    # 3) Mark price
    try:
        mp = futures_mark_price(symbol)
        mp_ok = (mp is not None)
        if mp_ok:
            details["mark_price"] = mp
        else:
            details["mark_price_error"] = f"No mark price for {symbol}"
    except Exception as e:
        mp_ok = False
        details["mark_price_error"] = str(e)

    ok = ping_ok and signed_ok and mp_ok
    payload = {
        "ok": ok,
        "binance_ping": ping_ok,
        "signed_balance_ok": signed_ok,
        "mark_price_ok": mp_ok,
        "details": details,
        "cached": False,
        "ttl_seconds": _HEALTH_TTL,
    }

    _health_cache["ts"] = now
    _health_cache["payload"] = dict(payload)
    return HealthResponse(**payload)






















