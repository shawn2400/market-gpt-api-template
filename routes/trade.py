# routes/trade.py
from __future__ import annotations

import logging
from typing import Dict, Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator

from utils.auth import require_api_key
from utils.trade_executor import execute_trade_live

logger = logging.getLogger("algogpt.routes.trade")

router = APIRouter(
    prefix="/trade",
    tags=["Trades"],
    dependencies=[Depends(require_api_key)],
)


# ────────────────────────────────────────────────────────────────────────────────
# Models
# ────────────────────────────────────────────────────────────────────────────────
class TradeRequest(BaseModel):
    """
    תומך בשלושה מצבי הקצאה: budget_usd | budget | quantity.
    לפחות אחד מהם חייב להיות חיובי בביצוע אמיתי (dry_run=False).
    """
    model_config = ConfigDict(extra="ignore")

    # Core
    symbol: str = Field(..., example="BTCUSDT")
    side: str = Field(..., example="BUY", description="BUY/SELL")
    leverage: int = Field(10, example=10, description="Binance Futures leverage (1..125)")

    # Allocation
    budget_usd: Optional[float] = Field(None, description="תקציב ב-USD (מועדף). שקול ל-budget.")
    budget: Optional[float] = Field(None, description="Alias ישן ל-budget_usd (זהה לחלוטין)")
    quantity: Optional[float] = Field(None, example=0.001, description="כמות בחוזה/מטבע")

    # Entry/Exit
    entry: float | None = Field(None, example=28500.5, description="מחיר כניסה; None = כניסה דינמית")
    sl: float | None = Field(None, example=28000.0, description="Stop-Loss price (LIMIT/STOP)")
    tp: float | None = Field(None, example=29500.0, description="Take-Profit price (LIMIT/TAKE_PROFIT)")

    tp_targets: Optional[List[float]] = Field(None, description="רשימת יעדי TP (מחירים)")
    tp_splits: Optional[List[float]] = Field(None, description="משקלי חלוקה ל-TP (שברים שסכומם ≤ 1; האחרון סוגר יתרה)")
    sl_targets: Optional[List[float]] = Field(None, description="רשימת מחירי SL מדרגיים")
    sl_splits: Optional[List[float]] = Field(None, description="משקלי חלוקה ל-SL")

    # Flags
    dry_run: bool = Field(False, description="True = סימולציה בלבד (ללא שליחה אמיתית)")
    confirm_first: bool = Field(True, description="דרוש אישור בטלגרם לפני ביצוע")
    telegram_chat_id: Optional[int] = Field(None, description="מס׳ צ׳אט לאישור (נדרש אם confirm_first=True)")

    # ───────── Validators / Normalizers (Pydantic v2) ─────────
    @field_validator("symbol", mode="before")
    @classmethod
    def _sym_upper(cls, v: Any) -> str:
        if not isinstance(v, str):
            raise ValueError("symbol must be string")
        v2 = v.strip().upper()
        if not v2:
            raise ValueError("symbol must be non-empty")
        return v2

    @field_validator("side", mode="before")
    @classmethod
    def _side_upper_check(cls, v: Any) -> str:
        if not isinstance(v, str):
            raise ValueError("side must be string")
        s = v.strip().upper()
        if s not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL")
        return s

    @field_validator("leverage")
    @classmethod
    def _lev_range(cls, v: int) -> int:
        if v < 1 or v > 125:
            raise ValueError("leverage must be between 1 and 125")
        return v

    @field_validator("entry", "sl", "tp")
    @classmethod
    def _positive_price_or_none(cls, v: Optional[float]) -> Optional[float]:
        if v is None:
            return v
        if v <= 0:
            raise ValueError("price fields must be > 0")
        return float(v)

    @field_validator("tp_targets", "sl_targets")
    @classmethod
    def _targets_positive(cls, v: Optional[List[float]]) -> Optional[List[float]]:
        if v is None:
            return v
        if any(x <= 0 for x in v):
            raise ValueError("all target prices must be > 0")
        return [float(x) for x in v]

    @field_validator("tp_splits", "sl_splits")
    @classmethod
    def _splits_range(cls, v: Optional[List[float]]) -> Optional[List[float]]:
        if v is None:
            return v
        if any(x < 0 for x in v):
            raise ValueError("all splits must be >= 0")
        return [float(x) for x in v]

    @model_validator(mode="after")
    def _post_validations(self) -> "TradeRequest":
        if self.tp_splits is not None and self.tp_targets is not None:
            if len(self.tp_splits) != len(self.tp_targets):
                raise ValueError("tp_splits length must match tp_targets length")
            if sum(self.tp_splits) > 1.0000001:
                raise ValueError("sum(tp_splits) must be ≤ 1.0")

        if self.sl_splits is not None and self.sl_targets is not None:
            if len(self.sl_splits) != len(self.sl_targets):
                raise ValueError("sl_splits length must match sl_targets length")
            if sum(self.sl_splits) > 1.0000001:
                raise ValueError("sum(sl_splits) must be ≤ 1.0")

        # אם confirm_first=True אך אין chat_id — לא נחסום dry_run כדי לבדוק זרימה
        return self


class TradeResponse(BaseModel):
    ok: bool = True
    error: str | None = None
    result: Dict[str, Any] | None = None


# ────────────────────────────────────────────────────────────────────────────────
# Route
# ────────────────────────────────────────────────────────────────────────────────
@router.post("/execute", response_model=TradeResponse, response_class=JSONResponse)
async def post_trade_execute(req: TradeRequest) -> TradeResponse:
    """
    טרייד דינמי מלא:
      • Quality Gate לייט
      • כניסה HYBRID (LIMIT+STOP) עם הסלמה ל-MARKET אם מוצדק
      • TP/SL (כולל מדרגות) כ-reduceOnly
      • ב-dry_run מוחזר תמיד OK עם פירוט gate/risk/תכנון, ללא שליחה אמיתית
    """
    try:
        # נרמול הקצאה: budget_effective (USD)
        budget_effective: Optional[float] = None
        if req.budget_usd is not None and req.budget_usd > 0:
            budget_effective = float(req.budget_usd)
        elif req.budget is not None and req.budget > 0:
            budget_effective = float(req.budget)

        # בביצוע אמיתי — דרוש לפחות אחד > 0
        if not req.dry_run:
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

        logger.info(
            {
                "event": "trade_execute_request",
                "symbol": req.symbol,
                "side": req.side,
                "lev": req.leverage,
                "dry": req.dry_run,
                "has_budget": budget_effective is not None,
                "has_qty": req.quantity is not None,
            }
        )

        result = await execute_trade_live(**args)

        if not result or not result.get("ok", False):
            return TradeResponse(
                ok=False,
                error=(result or {}).get("reason") or (result or {}).get("error") or "execution_failed",
                result=result,
            )

        return TradeResponse(ok=True, result=result)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("trade_execute_failed")
        raise HTTPException(status_code=500, detail=str(e))
































































































































































































































































































































































































































































































































































































































































