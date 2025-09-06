# routes/executor.py
from __future__ import annotations
import logging
from typing import Dict, Any, List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from utils.auth import require_api_key

# ניהול טריידים
try:
    from utils.open_trade_manager import manage_open_trades, bulk_manage_trades  # type: ignore
except Exception:
    manage_open_trades = None  # type: ignore
    bulk_manage_trades = None  # type: ignore

# נתוני Binance
try:
    from utils.binance_client import (  # type: ignore
        futures_balance,
        get_open_positions,
        futures_mark_price,
        exchange_info as _exchange_info_primary,
    )
except Exception:
    futures_balance = None
    get_open_positions = None
    futures_mark_price = None
    _exchange_info_primary = None

# Cache info
try:
    from utils import exchange_info_cache as _ex_cache  # type: ignore
except Exception:
    _ex_cache = None

logger = logging.getLogger("algogpt.executor")

router = APIRouter(
    prefix="/executor",
    tags=["Executor"],
    dependencies=[Depends(require_api_key)],
)

# ===================== Models =====================
class TradeRequest(BaseModel):
    symbol: str
    side: str
    qty: float
    entry_price: float
    sl_price: float
    tp_price: float
    leverage: int = 10
    position_side: str = "BOTH"

class BulkTradeRequest(BaseModel):
    trades: List[TradeRequest]

# ===================== Helpers =====================
def _safe_exchange_info() -> Dict[str, Any]:
    if callable(_exchange_info_primary):
        try:
            info = _exchange_info_primary()
            if isinstance(info, dict) and info: return info
        except Exception as e:
            logger.warning("[executor] exchange_info primary failed: %s", e)

    if _ex_cache:
        for fn_name in ("get", "get_exchange_info", "exchange_info"):
            try:
                fn = getattr(_ex_cache, fn_name, None)
                if callable(fn):
                    info = fn()
                    if isinstance(info, dict) and info: return info
            except Exception as e:
                logger.warning("[executor] exchange_info cache.%s failed: %s", fn_name, e)

    return {"symbols": []}

def _extract_symbols(info: Dict[str, Any]) -> List[str]:
    syms: List[str] = []
    if not isinstance(info, dict): return syms
    arr = info.get("symbols") or info.get("data") or []
    if not isinstance(arr, list): return syms
    for it in arr:
        try:
            s = str(it.get("symbol") or "").upper().strip()
            if not s: continue
            status = str(it.get("status") or it.get("tradeStatus") or "TRADING").upper()
            ct = str(it.get("contractType") or "").upper()
            if status == "TRADING" and (not ct or ct in ("PERPETUAL", "CURRENT_QUARTER", "NEXT_QUARTER")):
                syms.append(s)
        except Exception:
            continue
    if not syms:
        syms = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    return sorted(set(syms))

# ===================== Endpoints =====================
@router.post("/trade")
async def open_trade(req: TradeRequest) -> Dict[str, Any]:
    if not callable(manage_open_trades):
        raise HTTPException(status_code=500, detail="trade manager not available")
    try:
        result = manage_open_trades(
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
    except Exception as e:
        logger.exception("[executor] trade error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/bulk")
async def open_bulk(req: BulkTradeRequest) -> Dict[str, Any]:
    if not callable(bulk_manage_trades):
        raise HTTPException(status_code=500, detail="bulk trade manager not available")
    try:
        trades = [t.dict() for t in req.trades]
        results = bulk_manage_trades(trades)
        return {"ok": True, "results": results}
    except Exception as e:
        logger.exception("[executor] bulk error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/status")
async def executor_status() -> Dict[str, Any]:
    return {"ok": True, "status": "running"}

@router.get("/open-positions")
@router.get("/positions")
@router.get("/positions/open")
async def executor_open_positions() -> Dict[str, Any]:
    try:
        if callable(get_open_positions):
            pos = get_open_positions()
            return {"ok": True, "items": pos}
        return {"ok": True, "items": []}
    except Exception as e:
        logger.exception("[executor] open-positions error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/balance")
async def executor_balance() -> Dict[str, Any]:
    try:
        if callable(futures_balance):
            bal = futures_balance()
            return {"ok": True, "balances": bal}
        return {"ok": True, "balances": []}
    except Exception as e:
        logger.exception("[executor] balance error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/mark-price")
async def executor_mark_price(symbol: str = Query(...)) -> Dict[str, Any]:
    sym = (symbol or "").upper().strip()
    if not sym:
        raise HTTPException(status_code=400, detail="symbol is required")
    try:
        if callable(futures_mark_price):
            px = futures_mark_price(sym)
            return {"ok": True, "symbol": sym, "markPrice": px}
        raise RuntimeError("mark price provider not available")
    except Exception as e:
        logger.exception("[executor] mark-price error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/exchange-info")
async def executor_exchange_info() -> Dict[str, Any]:
    try:
        info = _safe_exchange_info()
        return {"ok": True, "info": info}
    except Exception as e:
        logger.exception("[executor] exchange-info error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/symbols")
@router.get("/symbols/allowed")
async def executor_symbols() -> Dict[str, Any]:
    try:
        info = _safe_exchange_info()
        syms = _extract_symbols(info)
        return {"ok": True, "items": syms}
    except Exception as e:
        logger.exception("[executor] symbols error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/close")
async def close_position(symbol: str) -> Dict[str, Any]:
    """
    סוגר פוזיציה קיימת ב־Binance (Market).
    """
    try:
        if not callable(get_open_positions):
            raise HTTPException(status_code=500, detail="positions provider not available")
        pos = get_open_positions()
        sym = (symbol or "").upper()
        for p in pos:
            if p.get("symbol") == sym and float(p.get("positionAmt") or 0) != 0:
                side = "SELL" if float(p["positionAmt"]) > 0 else "BUY"
                from utils.trade_executor import execute_trade_live
                res = execute_trade_live(
                    symbol=sym,
                    side=side,
                    budget=abs(float(p["positionAmt"]) * float(p.get("entryPrice", 0))),
                    leverage=int(p.get("leverage", 10)),
                    reduce_only=True,
                )
                return {"ok": True, "result": res}
        return {"ok": False, "error": f"No open position for {sym}"}
    except Exception as e:
        logger.exception("[executor] close error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

































