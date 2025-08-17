# routes/trade.py
from __future__ import annotations

import logging
from typing import Optional, Literal, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Body
from pydantic import BaseModel, Field

# --- Auth (עם fallback אם הפונקציה לא קיימת עדיין) ---
try:
    from utils.auth import require_bearer_token  # type: ignore
except Exception:
    # ⚠️ Fallback זמני: לא מבצע אימות. מומלץ לתקן את utils/auth.py ולהחזיר את הייבוא המקורי.
    def require_bearer_token():
        return None

from utils.sl_tp_utils import calculate_sl_tp
from utils.binance_trader import binance_futures_trade

# --- Anchor (ננסה shim ואז ניפול ל-btc_anchor) ---
try:
    from utils.anchor import evaluate_anchor, AnchorDecision  # shim לתאימות
except Exception:
    from utils.btc_anchor import evaluate_anchor, AnchorDecision  # גיבוי ישיר

from utils.quality import compute_quality

logger = logging.getLogger(__name__)

router = APIRouter(
    tags=["Trades"],
    dependencies=[Depends(require_bearer_token)],
)

SideLiteral = Literal["LONG", "SHORT"]

# ---------- Models ----------

class SLTPRequest(BaseModel):
    symbol: str = Field(..., example="BTCUSDT")
    direction: SideLiteral
    entry: float = Field(..., gt=0, example=65000)
    atr: Optional[float] = Field(None, gt=0, description="Optional ATR to refine SL/TP")

class SLTP3Response(BaseModel):
    symbol: str
    direction: SideLiteral
    sl: float
    tp1: float
    tp2: float

class TradeExecuteRequest(BaseModel):
    symbol: str = Field(..., example="BTCUSDT")
    side: SideLiteral
    budget: float = Field(..., gt=0, example=100)
    leverage: int = Field(..., ge=1, le=125, example=10)
    entry: Optional[float] = Field(None, gt=0)
    sl: Optional[float] = Field(None, gt=0)
    tp: Optional[float] = Field(None, gt=0)
    atr: Optional[float] = Field(None, gt=0, description="Optional ATR for SL/TP calculation")
    dry_run: bool = Field(True, description="Default: simulate only (no live orders)")

class TradeExecuteResponse(BaseModel):
    status: str = Field(default="ok", description="ok / error")
    result: Dict[str, Any]

class ErrorResponse(BaseModel):
    detail: str

# ---------- Dependencies ----------

async def _anchor_dep(payload: TradeExecuteRequest = Body(...)) -> AnchorDecision:
    # שימוש ב-anchor להחלטת ALLOW/HARD/SOFT
    return evaluate_anchor(payload.side)

# ---------- Endpoints ----------

@router.post(
    "/sltp",
    operation_id="postTradeSltp",
    response_model=SLTP3Response,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
)
async def post_sltp(payload: SLTPRequest = Body(...)) -> SLTP3Response:
    sl, tp1 = calculate_sl_tp(entry_price=payload.entry, direction=payload.direction, atr=payload.atr)
    if payload.direction == "LONG":
        tp2 = round(tp1 + (tp1 - payload.entry) * 0.4, 6)
    else:
        tp2 = round(tp1 - (payload.entry - tp1) * 0.4, 6)
    return SLTP3Response(
        symbol=payload.symbol.upper(),
        direction=payload.direction,
        sl=sl, tp1=tp1, tp2=tp2,
    )

@router.post(
    "/execute",
    operation_id="postTradeExecute",
    response_model=TradeExecuteResponse,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
)
async def post_execute(
    payload: TradeExecuteRequest = Body(...),
    anchor: AnchorDecision = Depends(_anchor_dep),
) -> TradeExecuteResponse:
    symbol = payload.symbol.upper()
    side = payload.side
    entry = payload.entry
    sl = payload.sl
    tp = payload.tp

    # 1) Anchor gate: HARD או הסלמה ל-HARD חוסמים
    if not anchor.allow:
        raise HTTPException(status_code=400, detail=f"blocked by BTC anchor: {anchor.reason}")

    # 2) Auto-calc SL/TP אם חסר (דורש entry)
    if (sl is None or tp is None):
        if entry is None:
            raise HTTPException(status_code=400, detail="entry is required when auto-calculating SL/TP")
        sl_auto, tp_auto = calculate_sl_tp(entry_price=entry, direction=side, atr=payload.atr)
        sl = sl if sl is not None else sl_auto
        tp = tp if tp is not None else tp_auto

    # 3) Quality scoring (תמיד מוחזר)
    quality = compute_quality(
        symbol=symbol, side=side, entry=entry, sl=sl, tp=tp,
        leverage=payload.leverage, budget=payload.budget,
        anchor=anchor, atr=payload.atr,
    )

    # 4) DRY-RUN
    if payload.dry_run:
        result = {
            "dry_run": True,
            "symbol": symbol,
            "side": side,
            "entry": float(entry) if entry is not None else None,
            "sl": float(sl) if sl is not None else None,
            "tp": float(tp) if tp is not None else None,
            "budget": float(payload.budget),
            "leverage": int(payload.leverage),
            "quality_score": quality["quality_score"],
            "success_pct": quality["success_pct"],
            "anchor": {
                "mode_requested": anchor.mode_requested,
                "mode_applied": anchor.mode_applied,
                "bias": anchor.bias,
                "score": anchor.score,
                "severity": anchor.severity,
                "reason": anchor.reason,
            },
            "note": "No orders sent (dry_run=true).",
        }
        return TradeExecuteResponse(status="ok", result=result)

    # 5) LIVE
    try:
        trade_result = await binance_futures_trade(
            symbol=symbol,
            side=side,
            entry=float(entry) if entry is not None else None,
            sl=float(sl) if sl is not None else None,
            tp=float(tp) if tp is not None else None,
            leverage=int(payload.leverage),
            budget=float(payload.budget),
            quantity=None,
            market_type="futures",
            cid_prefix="algogpt",
        )
        # שילוב הנתונים ל־result
        trade_result = {
            **trade_result,
            "quality_score": quality["quality_score"],
            "success_pct": quality["success_pct"],
            "anchor": {
                "mode_requested": anchor.mode_requested,
                "mode_applied": anchor.mode_applied,
                "bias": anchor.bias,
                "score": anchor.score,
                "severity": anchor.severity,
                "reason": anchor.reason,
            },
        }
        return TradeExecuteResponse(status="ok", result=trade_result)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Trade execution failed")
        raise HTTPException(status_code=400, detail=f"trade failed: {e}")















































































































































































































































































































