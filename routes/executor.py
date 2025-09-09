# routes/executor.py
from __future__ import annotations
import logging
from typing import Dict, Any, Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, ConfigDict

from utils.auth import require_api_key
from utils.binance_client import (
    fapi_ping,
    futures_open_positions_safe,
    futures_balance,
    futures_mark_price,
    futures_exchange_info_safe,
)
from utils.trade_executor import execute_trade_live

logger = logging.getLogger("algogpt.routes.executor")

router = APIRouter(
    prefix="/executor",
    tags=["Executor"],
    dependencies=[Depends(require_api_key)],
)

# ===== Models =====
class ExecTradeRequest(BaseModel):
    """בקשה מינימלית לטרייד דרך /executor/trade — עם תמיכה מלאה בהקצאה."""
    model_config = ConfigDict(extra="ignore")

    symbol: str = Field(..., examples=["BTCUSDT"])
    side: str = Field(..., examples=["BUY", "SELL"])
    leverage: int = Field(10, ge=1, le=125)

    # Allocation (לפחות אחד > 0 כשלא dry_run)
    budget_usd: Optional[float] = Field(None, ge=0, description="תקציב ב-USD (מועדף)")
    budget: Optional[float] = Field(None, ge=0, description="שם ישן — שקול ל-budget_usd")
    quantity: Optional[float] = Field(None, ge=0)

    # Entry/Exit (אופציונלי)
    entry: Optional[float] = Field(None)
    sl: Optional[float] = Field(None)
    tp: Optional[float] = Field(None)
    tp_targets: Optional[List[float]] = None
    tp_splits: Optional[List[float]] = None
    sl_targets: Optional[List[float]] = None
    sl_splits: Optional[List[float]] = None

    # Flags
    dry_run: bool = Field(True, description="True = סימולציה בלבד")
    confirm_first: bool = Field(True, description="אישור בטלגרם לפני ביצוע")
    telegram_chat_id: Optional[int] = Field(None)

@router.get("/ping")
async def ping() -> Dict[str, Any]:
    try:
        return {"ok": bool(fapi_ping())}
    except Exception as e:
        logger.warning("executor/ping failed: %s", e)
        return {"ok": False}

@router.get("/status")
async def status() -> Dict[str, Any]:
    return {"ok": True, "status": "running"}

@router.get("/positions")
async def open_positions(symbol: Optional[str] = Query(None)) -> Dict[str, Any]:
    try:
        return {"ok": True, "positions": futures_open_positions_safe(symbol)}
    except Exception as e:
        logger.error("positions failed: %s", e)
        raise HTTPException(500, str(e))

@router.get("/balance")
async def balance() -> Dict[str, Any]:
    try:
        return {"ok": True, "balances": futures_balance()}
    except Exception as e:
        logger.error("balance failed: %s", e)
        raise HTTPException(500, str(e))

@router.get("/mark-price")
async def mark_price(symbol: str = Query(..., min_length=3)) -> Dict[str, Any]:
    try:
        px = futures_mark_price(symbol)
        if px is None:
            raise RuntimeError("mark price unavailable")
        return {"ok": True, "symbol": symbol.upper(), "markPrice": px}
    except Exception as e:
        logger.error("mark-price failed: %s", e)
        raise HTTPException(500, str(e))

@router.get("/exchange-info")
async def exchange_info() -> Dict[str, Any]:
    try:
        return {"ok": True, "info": futures_exchange_info_safe()}
    except Exception as e:
        logger.error("exchange-info failed: %s", e)
        raise HTTPException(500, str(e))

@router.post("/trade")
async def trade(req: ExecTradeRequest) -> Dict[str, Any]:
    """נרמול הקצאה → הפעלה דרך execute_trade_live (זהה לסכמה של /trade/execute)."""
    try:
        # Normalize allocation
        budget_effective: Optional[float] = None
        if req.budget_usd and req.budget_usd > 0:
            budget_effective = float(req.budget_usd)
        elif req.budget and req.budget > 0:
            budget_effective = float(req.budget)

        args: Dict[str, Any] = {
            "symbol": req.symbol,
            "side": req.side,
            "leverage": req.leverage,
            "dry_run": req.dry_run,
            "entry": req.entry,
            "sl": req.sl,
            "tp": req.tp,
            "tp_targets": req.tp_targets,
            "tp_splits": req.tp_splits,
            "sl_targets": req.sl_targets,
            "sl_splits": req.sl_splits,
            "confirm_first": req.confirm_first,
            "telegram_chat_id": req.telegram_chat_id,
        }
        if budget_effective is not None:
            args["budget"] = budget_effective
        if req.quantity is not None:
            args["quantity"] = req.quantity

        res = await execute_trade_live(**args)
        ok = bool(res and res.get("ok", False))
        status_code = 200 if ok or req.dry_run else 409  # ביצוע אמיתי שנדחה → 409
        if not ok:
            # נשמור סיבה מובנת לצריכת לקוח/טלגרם
            return JSONResponse({"ok": False, "result": res, "reason": res.get("reason")}, status_code=status_code)
        return {"ok": True, "result": res}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("trade failed: %s", e)
        raise HTTPException(500, str(e))
































