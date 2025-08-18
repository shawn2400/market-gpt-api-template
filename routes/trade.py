# routes/trade.py
from __future__ import annotations

import os
import logging
from typing import Optional, Literal, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Body
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# --- Auth (עם fallback אם הפונקציה לא קיימת עדיין) ---
try:
    from utils.auth import require_bearer_token  # type: ignore
except Exception:
    def require_bearer_token():
        return None

# --- SL/TP ---
try:
    from utils.sl_tp_utils import calculate_sl_tp  # type: ignore
except Exception as e:
    raise RuntimeError(f"utils.sl_tp_utils.calculate_sl_tp required: {e}")

# --- Binance trade executor (LIVE) ---
try:
    from utils.binance_trader import binance_futures_trade  # type: ignore
except Exception:
    binance_futures_trade = None

# --- Anchor (ננסה shim ואז ניפול ל-btc_anchor) ---
try:
    from utils.anchor import evaluate_anchor, AnchorDecision  # type: ignore
except Exception:
    try:
        from utils.btc_anchor import evaluate_anchor, AnchorDecision  # type: ignore
    except Exception as e:
        raise RuntimeError(f"Anchor module required: {e}")

# --- Quality (ננסה את השם ההיסטורי; אם אין, נייבא מהקובץ אצלך) ---
_compute_quality = None
try:
    from utils.quality import compute_quality as _compute_quality  # type: ignore
except Exception:
    try:
        # בחלק מהקוד ההיסטורי compute_quality הופיע בתוך quantity_utils
        from utils.quantity_utils import compute_quality as _compute_quality  # type: ignore
    except Exception:
        _compute_quality = None

# --- Risk module (בחירה אוטומטית של תקציב/מינוף/כמות) ---
_risk_suggest = None
try:
    from utils.risk import suggest_budget_and_leverage as _risk_suggest  # type: ignore
except Exception:
    _risk_suggest = None

# --- דגלי מערכת ---
EXECUTE_TRADES = str(os.getenv("EXECUTE_TRADES", "false")).strip().lower() in ("1", "true", "yes", "on")
MAX_LEVERAGE_ENV = int(os.getenv("MAX_LEVERAGE", "35") or "35")

def _env_float(key: str, default: float) -> float:
    try:
        return float((os.getenv(key, "") or "").strip() or default)
    except Exception:
        return default

def _get_equity_usdt() -> float:
    """
    מקור להון עבודה עבור מודול הסיכון.
    ניתן להזין ב־.env:
      TRADING_EQUITY_USDT  או  ACCOUNT_EQUITY_USDT
    ברירת מחדל סבירה אם לא הוגדר – 2,000 USDT.
    """
    for k in ("TRADING_EQUITY_USDT", "ACCOUNT_EQUITY_USDT"):
        v = os.getenv(k, "").strip()
        if v:
            try:
                return float(v)
            except Exception:
                pass
    return 2000.0

# ---------- Models ----------

SideLiteral = Literal["LONG", "SHORT"]

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
    budget: Optional[float] = Field(None, gt=0, example=100, description="Optional. If omitted, risk engine will suggest.")
    leverage: Optional[int] = Field(None, ge=1, le=125, example=10, description="Optional. If omitted, risk engine will suggest.")
    entry: Optional[float] = Field(None, gt=0)
    sl: Optional[float] = Field(None, gt=0)
    tp: Optional[float] = Field(None, gt=0)
    atr: Optional[float] = Field(None, gt=0, description="Optional ATR for SL/TP & risk.")
    dry_run: bool = Field(True, description="Default: simulate only (no live orders)")

class TradeExecuteResponse(BaseModel):
    status: str = Field(default="ok", description="ok / error")
    result: Dict[str, Any]

class ErrorResponse(BaseModel):
    detail: str

# ---------- Router ----------

router = APIRouter(
    tags=["Trades"],
    dependencies=[Depends(require_bearer_token)],
)

# ---------- Helpers ----------

async def _anchor_dep(payload: TradeExecuteRequest = Body(...)) -> AnchorDecision:
    return evaluate_anchor(payload.side)

def _compute_quality_safe(
    *,
    symbol: str,
    side: SideLiteral,
    entry: Optional[float],
    sl: Optional[float],
    tp: Optional[float],
    leverage: int,
    budget: float,
    anchor: AnchorDecision,
    atr: Optional[float] = None,
) -> Dict[str, Any]:
    """
    עוטף את compute_quality – ואם אין מודול/שגיאה, מחזיר ניתוח בסיסי.
    """
    if _compute_quality:
        try:
            return _compute_quality(
                symbol=symbol, side=side, entry=entry, sl=sl, tp=tp,
                leverage=leverage, budget=budget, anchor=anchor, atr=atr,
            )
        except Exception as e:
            logger.warning("compute_quality failed: %s", e)

    # fallback פשוט: RR + מינוף → ציון
    if entry is None or sl is None or tp is None:
        return {
            "quality_score": 5.0,
            "success_pct": 50.0,
            "components": {"note": "fallback quality (missing pricing inputs)"},
        }

    if side == "LONG":
        risk = max(0.0, entry - sl)
        reward = max(0.0, tp - entry)
    else:
        risk = max(0.0, sl - entry)
        reward = max(0.0, entry - tp)
    rr = (reward / risk) if risk > 1e-12 else 0.0
    # מדרוג: RR=2 → 9-10, RR=1 → ~6, נמוך מ־0.5 → ~3-4
    base = max(0.0, min(10.0, 4.0 + 3.0 * rr))
    # ענישה קלה על מינוף גבוה
    lev_pen = min(3.0, max(0.0, (leverage - 10) / 10.0))
    score = round(max(0.0, min(10.0, base - lev_pen)), 2)
    # success% היוריסטי
    success = round(35 + (score / 10.0) * 40.0, 2)  # 35..75
    return {
        "quality_score": score,
        "success_pct": success,
        "components": {"note": "basic RR-based fallback"},
    }

def _ensure_entry_for_auto_sltp(entry: Optional[float], sl: Optional[float], tp: Optional[float]) -> None:
    if (sl is None or tp is None) and entry is None:
        raise HTTPException(status_code=400, detail="entry is required when auto-calculating SL/TP")

# ---------- Endpoints ----------

@router.post(
    "/sltp",
    operation_id="postTradeSltp",
    response_model=SLTP3Response,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
)
async def post_sltp(payload: SLTPRequest = Body(...)) -> SLTP3Response:
    sl, tp1 = calculate_sl_tp(entry_price=payload.entry, direction=payload.direction, atr=payload.atr)
    # TP2 – מדרג פשוט (40% מעבר למרחק TP1)
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

    # Anchor block?
    if not anchor.allow:
        raise HTTPException(status_code=400, detail=f"blocked by BTC anchor: {anchor.reason}")

    # SL/TP auto-calc if missing
    _ensure_entry_for_auto_sltp(entry, sl, tp)
    if sl is None or tp is None:
        sl_auto, tp_auto = calculate_sl_tp(entry_price=float(entry), direction=side, atr=payload.atr)
        sl = sl if sl is not None else sl_auto
        tp = tp if tp is not None else tp_auto

    # Defaults before risk-engine
    # אם המשתמש סיפק מינוף/תקציב – נתחיל מהם; אחרת נשתמש בריסק-אנג'ין כדי להציע.
    leverage = int(payload.leverage) if payload.leverage is not None else 10
    budget = float(payload.budget) if payload.budget is not None else _env_float("MAX_TRADE_BUDGET", 100.0)
    quantity: Optional[float] = None

    # Compute quality & success to serve as "confidence" for the risk engine
    quality = _compute_quality_safe(
        symbol=symbol, side=side, entry=entry, sl=sl, tp=tp,
        leverage=leverage, budget=budget, anchor=anchor, atr=payload.atr,
    )
    confidence = float(quality.get("success_pct", 50.0))

    # Risk engine suggestion (if available)
    risk_info = None
    if _risk_suggest and entry is not None and sl is not None:
        try:
            equity = _get_equity_usdt()
            risk_rec = _risk_suggest(
                symbol=symbol, side=side, entry=float(entry), sl=float(sl), tp=float(tp) if tp else None,
                equity_usdt=float(equity), confidence=confidence, atr=payload.atr,
                max_budget_usdt=_env_float("MAX_TRADE_BUDGET", 100.0),
                max_leverage=int(os.getenv("MAX_LEVERAGE", str(MAX_LEVERAGE_ENV)) or MAX_LEVERAGE_ENV),
            )
            # אם ההמלצה תקינה – נעדיף אותה, אלא אם המשתמש נעל פרמטרים במפורש
            if isinstance(risk_rec, dict) and risk_rec.get("ok"):
                risk_info = risk_rec
                if payload.budget is None:
                    budget = float(risk_rec["suggested"]["budget_usd"])
                if payload.leverage is None:
                    leverage = int(risk_rec["suggested"]["leverage"])
                # תמיד נשמח לקבל qty exchange-safe אם קיים
                quantity = float(risk_rec["suggested"]["qty"])
        except Exception as e:
            logger.warning("risk suggest failed: %s", e)

    # DRY RUN path
    if payload.dry_run or not EXECUTE_TRADES or binance_futures_trade is None:
        result = {
            "mode": "dry_run",
            "symbol": symbol,
            "side": side,
            "entry": float(entry) if entry is not None else None,
            "sl": float(sl) if sl is not None else None,
            "tp": float(tp) if tp is not None else None,
            "budget": float(budget),
            "leverage": int(leverage),
            "quantity": quantity,
            "quality_score": quality.get("quality_score"),
            "success_pct": quality.get("success_pct"),
            "anchor": {
                "mode_requested": anchor.mode_requested,
                "mode_applied": anchor.mode_applied,
                "bias": anchor.bias,
                "score": anchor.score,
                "severity": anchor.severity,
                "reason": anchor.reason,
            },
            "risk": risk_info,
            "note": "No orders sent (dry_run=true or EXECUTE_TRADES disabled)." if (payload.dry_run or not EXECUTE_TRADES) else "No executor available.",
        }
        return TradeExecuteResponse(status="ok", result=result)

    # LIVE path (EXECUTE_TRADES=true and executor available)
    try:
        trade_result = await binance_futures_trade(
            symbol=symbol,
            side=side,
            entry=float(entry) if entry is not None else None,
            sl=float(sl) if sl is not None else None,
            tp=float(tp) if tp is not None else None,
            leverage=int(leverage),
            budget=float(budget),
            quantity=quantity,            # אם risk הציע כמות מדויקת – נשתמש
            market_type="futures",
            cid_prefix="algogpt",
        )
        trade_result = {
            **trade_result,
            "quality_score": quality.get("quality_score"),
            "success_pct": quality.get("success_pct"),
            "anchor": {
                "mode_requested": anchor.mode_requested,
                "mode_applied": anchor.mode_applied,
                "bias": anchor.bias,
                "score": anchor.score,
                "severity": anchor.severity,
                "reason": anchor.reason,
            },
            "risk": risk_info,
        }
        return TradeExecuteResponse(status="ok", result=trade_result)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Trade execution failed")
        raise HTTPException(status_code=400, detail=f"trade failed: {e}")

















































































































































































































































































































