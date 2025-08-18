# routes/risk.py
from __future__ import annotations

import os
import logging
from typing import Optional, Literal, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Body
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# --- Auth (עם fallback אם אין מודול) ---
try:
    from utils.auth import require_bearer_token  # type: ignore
except Exception:
    def require_bearer_token():
        return None

# --- Risk core (מחשב תקציב/מינוף/כמות באופן חכם) ---
_risk_suggest = None
try:
    from utils.risk import suggest_budget_and_leverage as _risk_suggest  # type: ignore
except Exception:
    _risk_suggest = None

# --- חישוב כמות בדיוק בורסת Binance (פולבקים חכמים בפנים) ---
_calc_qty = None
try:
    from utils.calculate_quantity import calculate_quantity as _calc_qty  # type: ignore
except Exception:
    _calc_qty = None

Side = Literal["LONG", "SHORT"]

def _env_float(key: str, default: float) -> float:
    try:
        return float((os.getenv(key, "") or "").strip() or default)
    except Exception:
        return default

def _env_int(key: str, default: int) -> int:
    try:
        return int((os.getenv(key, "") or "").strip() or default)
    except Exception:
        return default

def _default_equity() -> float:
    for k in ("TRADING_EQUITY_USDT", "ACCOUNT_EQUITY_USDT"):
        v = os.getenv(k, "").strip()
        if v:
            try:
                return float(v)
            except Exception:
                pass
    return 2000.0

# ---------- Models ----------

class RiskSuggestRequest(BaseModel):
    symbol: str = Field(..., example="BTCUSDT")
    side: Side
    entry: float = Field(..., gt=0)
    sl: float = Field(..., gt=0)
    tp: Optional[float] = Field(None, gt=0)
    atr: Optional[float] = Field(None, gt=0)

    equity_usdt: Optional[float] = Field(None, gt=0, description="Account equity in USDT. If omitted, uses env or 2000.")
    confidence: Optional[float] = Field(55.0, ge=0, le=100, description="0..100. If absent, derived from quality/success externally.")

    max_budget_usdt: Optional[float] = Field(None, gt=0)
    max_leverage: Optional[int] = Field(None, ge=1, le=125)

class RiskSuggestResponse(BaseModel):
    ok: bool = True
    suggested: Dict[str, Any]
    inputs: Dict[str, Any]
    constraints: Dict[str, Any] | None = None
    note: Optional[str] = None

class ErrorResponse(BaseModel):
    detail: str

# ---------- Router ----------

router = APIRouter(
    prefix="/risk",
    tags=["Risk"],
    dependencies=[Depends(require_bearer_token)],
)

# ---------- Helpers ----------

def _compute_rr(entry: float, sl: float, tp: Optional[float], side: Side) -> Dict[str, float]:
    if side == "LONG":
        risk = max(0.0, entry - sl)
        reward = max(0.0, (tp - entry) if tp else 0.0)
    else:
        risk = max(0.0, sl - entry)
        reward = max(0.0, (entry - tp) if tp else 0.0)
    rr = (reward / risk) if (risk > 1e-12 and reward > 0) else 0.0
    return {"risk": float(risk), "reward": float(reward), "rr": float(rr)}

# ---------- Endpoint ----------

@router.post(
    "/suggest",
    operation_id="postRiskSuggest",
    response_model=RiskSuggestResponse,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
)
async def post_risk_suggest(payload: RiskSuggestRequest = Body(...)) -> RiskSuggestResponse:
    symbol = payload.symbol.upper()
    side: Side = payload.side
    entry = float(payload.entry)
    sl = float(payload.sl)
    tp = float(payload.tp) if payload.tp is not None else None
    atr = float(payload.atr) if payload.atr is not None else None

    if entry <= 0 or sl <= 0:
        raise HTTPException(status_code=400, detail="entry and sl must be positive numbers")

    # constraints from env or request
    equity = float(payload.equity_usdt) if payload.equity_usdt else _default_equity()
    max_budget = float(payload.max_budget_usdt) if payload.max_budget_usdt else _env_float("MAX_TRADE_BUDGET", 100.0)
    max_leverage = int(payload.max_leverage) if payload.max_leverage else _env_int("MAX_LEVERAGE", 35)
    confidence = float(payload.confidence if payload.confidence is not None else 55.0)

    constraints = {
        "equity_usdt": equity,
        "max_budget_usdt": max_budget,
        "max_leverage": max_leverage,
        "confidence": confidence,
    }

    # --- Primary path: use utils.risk if קיים ---
    if _risk_suggest:
        try:
            res = _risk_suggest(
                symbol=symbol,
                side=side,
                entry=entry,
                sl=sl,
                tp=tp,
                equity_usdt=equity,
                confidence=confidence,
                atr=atr,
                max_budget_usdt=max_budget,
                max_leverage=max_leverage,
            )
            if isinstance(res, dict) and res.get("ok"):
                return RiskSuggestResponse(
                    ok=True,
                    suggested=res["suggested"],
                    inputs={"symbol": symbol, "side": side, "entry": entry, "sl": sl, "tp": tp, "atr": atr},
                    constraints=constraints,
                    note=res.get("note"),
                )
            # אם המודול החזיר not ok, ניפול לפולבק
            logger.warning("utils.risk returned not ok, falling back. reason=%s", res)
        except Exception as e:
            logger.warning("risk.suggest failed, falling back: %s", e)

    # --- Fallback: היוריסטיקה קלה + rounding דרך calculate_quantity אם אפשר ---
    rr_info = _compute_rr(entry, sl, tp, side)
    rr = rr_info["rr"]
    # יעד ריסק: 0.6%..1.5% מן ההון לפי confidence ו-RR
    base_risk_pct = 0.006 + max(0.0, min(0.9, (confidence - 50.0) / 50.0)) * 0.009  # ~0.6%..1.5%
    rr_boost = min(0.5, rr / 3.0)  # RR 3 → +0.5
    risk_pct = min(0.02, base_risk_pct + rr_boost * 0.01)  # מגבלה 2%

    target_risk_usd = equity * risk_pct
    # מרחק ל-SL בכסף ליחידה:
    sl_dist = abs(entry - sl)
    if sl_dist <= 0:
        raise HTTPException(status_code=400, detail="SL distance must be positive")
    # כמות לפי ריסק:
    qty_raw = target_risk_usd / sl_dist
    # הפוך לתקציב ומינוף:
    # אם לא ניתן לחשב תקציב מדויק, נקבע אותו עד max_budget והמינוף יישר כמות.
    budget_guess = min(max_budget, max(5.0, qty_raw * entry / 10.0))  # הערכה ראשונית
    leverage_guess = min(max_leverage, max(3, int(round((qty_raw * entry) / max(budget_guess, 1e-9)))))

    # אם יש calculate_quantity – נחשב כמות בורסאית בטוחה
    if _calc_qty:
        try:
            qty_ex = _calc_qty(symbol=symbol, entry_price=entry, leverage=float(leverage_guess), budget_usdt=float(budget_guess))
            if qty_ex and qty_ex > 0:
                qty_final = float(qty_ex)
                budget_final = budget_guess
                leverage_final = leverage_guess
            else:
                qty_final = float(qty_raw)
                budget_final = budget_guess
                leverage_final = leverage_guess
        except Exception:
            qty_final = float(qty_raw)
            budget_final = budget_guess
            leverage_final = leverage_guess
    else:
        qty_final = float(qty_raw)
        budget_final = budget_guess
        leverage_final = leverage_guess

    suggested = {
        "budget_usd": round(float(budget_final), 6),
        "leverage": int(leverage_final),
        "qty": round(float(qty_final), 6),
        "rr": rr,
        "risk_pct_of_equity": round(float(risk_pct) * 100.0, 3),
        "sl_distance": sl_dist,
        "calc_mode": "fallback",
    }

    return RiskSuggestResponse(
        ok=True,
        suggested=suggested,
        inputs={"symbol": symbol, "side": side, "entry": entry, "sl": sl, "tp": tp, "atr": atr},
        constraints=constraints,
        note="Fallback heuristic used (utils.risk unavailable or failed).",
    )



