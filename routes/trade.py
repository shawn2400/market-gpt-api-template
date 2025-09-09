# routes/trade.py
from __future__ import annotations
import logging
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ConfigDict

from utils.auth import require_api_key
from utils.trade_executor import execute_trade_live

logger = logging.getLogger("algogpt.routes.trade")

router = APIRouter(
    prefix="/trade",
    tags=["Trades"],
    dependencies=[Depends(require_api_key)],
)

class TradeRequest(BaseModel):
    """
    תומך בשלושה מצבי הקצאה: budget_usd | budget | quantity.
    לפחות אחד מהם חייב להיות חיובי. שדות עודפים ייגנרו (ignore).
    """
    model_config = ConfigDict(extra="ignore")

    symbol: str = Field(..., example="BTCUSDT")
    side: str = Field(..., example="BUY")  # BUY/SELL
    leverage: int = Field(10, example=10)

    # Allocation
    budget_usd: Optional[float] = Field(None, description="תקציב ב-USD (מועדף)")
    budget: Optional[float] = Field(None, description="שם ישן — שקול ל-budget_usd")
    quantity: Optional[float] = Field(None, example=0.001)

    # Entry/Exit
    entry: float | None = Field(None, example=28500.5, description="מחיר כניסה; אם None — כניסה דינמית")
    sl: float | None = Field(None, example=28000.0, description="Stop-Loss price (LIMIT/STOP)")
    tp: float | None = Field(None, example=29500.0, description="Take-Profit price (LIMIT/TAKE_PROFIT)")
    tp_targets: Optional[List[float]] = Field(None, description="רשימת יעדי TP (מחירים)")
    tp_splits: Optional[List[float]] = Field(None, description="חלוקת כמויות ל-TP (שברים שסוכמים ≤1; האחרון סוגר יתרה)")
    sl_targets: Optional[List[float]] = Field(None, description="רשימת מחירי SL מדרגיים")
    sl_splits: Optional[List[float]] = Field(None, description="חלוקת כמויות ל-SL")

    # Flags
    dry_run: bool = Field(False, description="True = סימולציה בלבד (ללא שליחה אמיתית)")
    confirm_first: bool = Field(True, description="דרוש אישור בטלגרם לפני ביצוע")
    telegram_chat_id: Optional[int] = Field(None, description="מס׳ צ׳אט לאישור")

class TradeResponse(BaseModel):
    ok: bool = True
    error: str | None = None
    result: Dict[str, Any] | None = None

@router.post("/execute", response_model=TradeResponse, response_class=JSONResponse)
async def post_trade_execute(req: TradeRequest) -> TradeResponse:
    """
    טרייד דינמי מלא: Gate איכות, כניסה היברידית (LIMIT+STOP) והסלמה ל-MARKET אם מוצדק,
    SL/TP (כולל סטים) כ-reduceOnly. ב-dry_run תמיד מוחזר OK עם gate details.
    """
    try:
        # נרמול הקצאה: budget_effective (USD)
        budget_effective: Optional[float] = None
        if req.budget_usd is not None and req.budget_usd > 0:
            budget_effective = float(req.budget_usd)
        elif req.budget is not None and req.budget > 0:
            budget_effective = float(req.budget)

        if not req.dry_run:
            # בביצוע אמיתי — דרוש לפחות אחד > 0
            if (not budget_effective or budget_effective <= 0) and (not req.quantity or req.quantity <= 0):
                raise HTTPException(status_code=422, detail="Either positive budget(_usd) or quantity must be provided")

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

        result = await execute_trade_live(**args)
        if not result or not result.get("ok", False):
            return TradeResponse(ok=False, error=(result or {}).get("reason") or (result or {}).get("error"), result=result)
        return TradeResponse(ok=True, result=result)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("trade_execute_failed")
        raise HTTPException(status_code=500, detail=str(e))






























































































































































































































































































































































































































































































































































































































































