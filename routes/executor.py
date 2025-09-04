# routes/executor.py
from __future__ import annotations
import logging
from typing import Dict, Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from utils.auth import require_api_key
from utils.open_trade_manager import manage_open_trades, bulk_manage_trades

# נתוני בורסה / סימבולים / מרק-פרייס / באלאנסים
try:
    from utils.binance_client import (
        futures_balance,
        get_open_positions,
        futures_mark_price,
        exchange_info as _exchange_info_primary,
    )
except Exception:  # שמור תאימות גם אם פונקציות מסוימות לא קיימות בריצה
    futures_balance = None
    get_open_positions = None
    futures_mark_price = None
    _exchange_info_primary = None  # type: ignore

# Fallback לקאש של Exchange Info אם קיים
try:
    from utils import exchange_info_cache as _ex_cache  # type: ignore
except Exception:
    _ex_cache = None  # type: ignore

logger = logging.getLogger("algogpt.executor")

router = APIRouter(
    prefix="/executor",
    tags=["Executor"],
    dependencies=[Depends(require_api_key)],
)

# ===================== Models =====================
class TradeRequest(BaseModel):
    symbol: str = Field(..., description="Trading symbol, e.g., BTCUSDT")
    side: str = Field(..., description="BUY or SELL")
    qty: float = Field(..., gt=0, description="Quantity in contracts")
    entry_price: float = Field(..., gt=0, description="Entry limit price")
    sl_price: float = Field(..., gt=0, description="Stop-loss price")
    tp_price: float = Field(..., gt=0, description="Take-profit price")
    leverage: int = Field(10, description="Leverage for the trade")
    position_side: str = Field("BOTH", description="BOTH | LONG | SHORT")


class BulkTradeRequest(BaseModel):
    trades: list[TradeRequest]


# ===================== Helpers =====================
def _safe_exchange_info() -> Dict[str, Any]:
    """
    מנסה להביא Exchange Info ממספר מקורות, עם פולבאק עדין.
    """
    # 1) נסה מהלקוח הראשי
    if callable(_exchange_info_primary):
        try:
            info = _exchange_info_primary()
            if isinstance(info, dict) and info:
                return info
        except Exception as e:
            logger.warning("[executor] exchange_info primary failed: %s", e)

    # 2) נסה מה-cache אם קיים
    if _ex_cache:
        for fn_name in ("get", "get_exchange_info", "exchange_info"):
            try:
                fn = getattr(_ex_cache, fn_name, None)
                if callable(fn):
                    info = fn()
                    if isinstance(info, dict) and info:
                        return info
            except Exception as e:
                logger.warning("[executor] exchange_info cache.%s failed: %s", fn_name, e)

    # 3) פולבאק ריק (לא זורקים שגיאה כדי לא “לשבור” זרימה)
    return {"symbols": []}


def _extract_symbols(info: Dict[str, Any]) -> List[str]:
    """
    חילוץ רשימת סימבולים “טריידבליים” ממבנה ExchangeInfo טיפוסי של ביננס.
    לא מניח שדות קשיחים; מתאמץ להיות סלחני.
    """
    syms: List[str] = []
    if not isinstance(info, dict):
        return syms
    arr = info.get("symbols") or info.get("data") or []
    if not isinstance(arr, list):
        return syms
    for it in arr:
        try:
            s = str(it.get("symbol") or "").upper().strip()
            if not s:
                continue
            status = str(it.get("status") or it.get("tradeStatus") or "TRADING").upper()
            # FUTURES: לעתים יש שדה contractType=PERPETUAL או deliveryDate=0
            ct = str(it.get("contractType") or "").upper()
            if status == "TRADING" and (not ct or ct in ("PERPETUAL", "CURRENT_QUARTER", "NEXT_QUARTER")):
                syms.append(s)
        except Exception:
            continue
    # אם אין כלום, פולבאק מינימלי
    if not syms:
        syms = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    return sorted(set(syms))


# ===================== Endpoints =====================
@router.post("/trade", summary="Open trade with SL/TP")
async def open_trade(req: TradeRequest, _: Any = Depends(require_api_key)) -> Dict[str, Any]:
    """
    פותח טרייד כולל Limit כניסה + Stop-Loss + Take-Profit.
    שומר תאימות לאחור ע"י שימוש ב-manage_open_trades כפי שקיים אצלך.
    """
    try:
        logger.info("[executor] trade request: %s", req.dict())
        result = manage_open_trades(  # type: ignore[call-arg]
            symbol=req.symbol,
            side=req.side,
            qty=req.qty,
            entry_price=req.entry_price,
            sl_price=req.sl_price,
            tp_price=req.tp_price,
            leverage=req.leverage,
            position_side=req.position_side,
        )
        if not isinstance(result, dict) or not result.get("ok"):
            raise HTTPException(status_code=400, detail=result if isinstance(result, dict) else {"ok": False})
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[executor] trade error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/bulk", summary="Open multiple trades")
async def open_bulk(req: BulkTradeRequest, _: Any = Depends(require_api_key)) -> Dict[str, Any]:
    """
    פותח מספר טריידים ברצף.
    """
    try:
        trades = [t.dict() for t in req.trades]
        logger.info("[executor] bulk request: %s", trades)
        results = bulk_manage_trades(trades)  # type: ignore[arg-type]
        return {"ok": True, "results": results}
    except Exception as e:
        logger.exception("[executor] bulk error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status", summary="Executor status")
async def executor_status(_: Any = Depends(require_api_key)) -> Dict[str, Any]:
    """
    מחזיר סטטוס בסיסי של ה־Executor (חי).
    """
    return {"ok": True, "status": "running"}


# ======== Aliases & Operational Info (שלא חזרו ב-OpenAPI והחזירו 404) ========

@router.get("/open-positions", summary="List open futures positions")
@router.get("/positions", summary="List open futures positions (alias)")
@router.get("/positions/open", summary="List open futures positions (alias)")
async def executor_open_positions(_: Any = Depends(require_api_key)) -> Dict[str, Any]:
    try:
        if callable(get_open_positions):
            pos = get_open_positions()  # type: ignore[call-arg]
            return {"ok": True, "items": pos}
        # אם לא זמינה הפונקציה, נחזיר מבנה ריק אך חוקי
        return {"ok": True, "items": []}
    except Exception as e:
        logger.exception("[executor] open-positions error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/balance", summary="Futures account balances")
async def executor_balance(_: Any = Depends(require_api_key)) -> Dict[str, Any]:
    try:
        if callable(futures_balance):
            bal = futures_balance()  # type: ignore[call-arg]
            return {"ok": True, "balances": bal}
        return {"ok": True, "balances": []}
    except Exception as e:
        logger.exception("[executor] balance error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/mark-price", summary="Futures mark price for a symbol")
async def executor_mark_price(
    symbol: str = Query(..., description="e.g. BTCUSDT")
) -> Dict[str, Any]:
    sym = (symbol or "").upper().strip()
    if not sym:
        raise HTTPException(status_code=400, detail="symbol is required")
    try:
        if callable(futures_mark_price):
            px = futures_mark_price(sym)  # type: ignore[call-arg]
            return {"ok": True, "symbol": sym, "markPrice": px}
        raise RuntimeError("mark price provider not available")
    except Exception as e:
        logger.exception("[executor] mark-price error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/exchange-info", summary="Raw exchange info (with cache fallback)")
async def executor_exchange_info(_: Any = Depends(require_api_key)) -> Dict[str, Any]:
    try:
        info = _safe_exchange_info()
        return {"ok": True, "info": info}
    except Exception as e:
        logger.exception("[executor] exchange-info error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/symbols", summary="Tradable symbols (derived)")
@router.get("/symbols/allowed", summary="Tradable symbols (alias)")
async def executor_symbols(_: Any = Depends(require_api_key)) -> Dict[str, Any]:
    try:
        info = _safe_exchange_info()
        syms = _extract_symbols(info)
        return {"ok": True, "items": syms}
    except Exception as e:
        logger.exception("[executor] symbols error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
































