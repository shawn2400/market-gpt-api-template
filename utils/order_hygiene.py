# utils/order_hygiene.py
from __future__ import annotations
from typing import Optional, Dict, Any, Tuple
from decimal import Decimal, ROUND_DOWN
import os, uuid

from utils.idempotency import claim as idp_claim
from utils.binance_client import (
    get_symbol_filters, place_limit_order, place_stop_market_order, place_take_profit_market
)
from utils.decision_log import log_decision

_SLIP_MAX_PCT = float(os.getenv("SLIPPAGE_MAX_PCT", "0.35"))
_POST_ONLY_DEFAULT = str(os.getenv("POST_ONLY_DEFAULT", "false")).lower() in ("1","true","yes","on")
_IDP_TTL = int(os.getenv("IDEMPOTENCY_DEFAULT_TTL_SEC", "120"))

def _fmt(x: float) -> str:
    return f"{x:.18f}".rstrip("0").rstrip(".")

def _quantize_price_qty(symbol: str, qty: float, price: Optional[float]) -> Tuple[Decimal, Optional[Decimal], Dict[str, Any]]:
    f = get_symbol_filters(symbol)
    step_str = f.get("stepSizeStr", "0.001")
    tick_str = f.get("tickSizeStr", "0.1")
    q = (Decimal(str(qty)) // Decimal(step_str)) * Decimal(step_str)
    p = None
    if price is not None:
        p = (Decimal(str(price)) // Decimal(tick_str)) * Decimal(tick_str)
    return q.quantize(Decimal(step_str), rounding=ROUND_DOWN), (p.quantize(Decimal(tick_str), rounding=ROUND_DOWN) if p else None), f

def _ensure_notional_ok(qty: Decimal, price: Optional[Decimal], f: Dict[str, Any]) -> None:
    min_notional = float(f.get("minNotional") or os.getenv("MIN_NOTIONAL_USDT", "5"))
    if price is not None:
        notional = float(qty) * float(price)
        if notional < min_notional:
            raise ValueError(f"min notional {min_notional} not met (got {notional:.4f})")

def _coerce_side(side: str) -> str:
    s = side.strip().upper()
    if s not in ("BUY","SELL"):
        raise ValueError("side must be BUY/SELL")
    return s

def _client_oid(prefix: str, symbol: str, tag: str) -> str:
    return f"{prefix}{symbol}:{tag}:{uuid.uuid4().hex[:10]}"

def _slippage_check(wish: float, limit_price: Optional[float]) -> None:
    try:
        if limit_price is None:
            return
        slip_pct = abs((limit_price - wish) / wish) * 100.0
        if slip_pct > _SLIP_MAX_PCT:
            raise ValueError(f"limit slippage {slip_pct:.3f}% > max {_SLIP_MAX_PCT}%")
    except Exception as e:
        raise ValueError(f"Slippage check failed: {e}")

# ── Public Safe wrappers ──────────────────────
def place_limit_safe(*, symbol: str, side: str, qty: float, limit_price: float,
                     post_only: Optional[bool] = None, reduce_only=False,
                     position_side=None, idp_key=None) -> Dict[str, Any]:
    s, side = symbol.upper().strip(), _coerce_side(side)
    q, p, f = _quantize_price_qty(s, qty, limit_price)
    _ensure_notional_ok(q, p, f)
    _slippage_check(limit_price, float(p))
    cid = _client_oid("LIM:", s, "open" if not reduce_only else "reduce")
    idp = idp_key or f"lim:{s}:{side}:{_fmt(float(q))}:{_fmt(float(p))}:{'ro' if reduce_only else 'nr'}"
    if not idp_claim(idp, _IDP_TTL): raise RuntimeError("duplicate limit order")
    resp = place_limit_order(
        symbol=s, side=side, quantity=float(q), price=float(p),
        time_in_force=("GTX" if (post_only if post_only is not None else _POST_ONLY_DEFAULT) else "GTC"),
        post_only=bool(post_only if post_only is not None else _POST_ONLY_DEFAULT),
        reduce_only=reduce_only, position_side=position_side, new_client_order_id=cid
    )
    log_decision(event="place_limit", symbol=s, side=side, extra={"qty": float(q), "price": float(p)})
    return resp

def place_stop_market_safe(*, symbol: str, side: str, stop_price: float, qty: Optional[float] = None,
                           reduce_only=True, position_side=None, idp_key=None) -> Dict[str, Any]:
    s, side = symbol.upper().strip(), _coerce_side(side)
    q = None
    f = get_symbol_filters(s)
    if qty is not None:
        q, _, f = _quantize_price_qty(s, qty, None)
        _ensure_notional_ok(q, Decimal(stop_price), f)
    cid = _client_oid("STP:", s, "close" if reduce_only else "open")
    idp = idp_key or f"stp:{s}:{side}:{_fmt(stop_price)}:{_fmt(float(q) if q else 0)}:{'ro' if reduce_only else 'nr'}"
    if not idp_claim(idp, _IDP_TTL): raise RuntimeError("duplicate stop order")
    resp = place_stop_market_order(symbol=s, side=side, stop_price=stop_price,
                                   quantity=(float(q) if q else None),
                                   reduce_only=reduce_only, position_side=position_side,
                                   new_client_order_id=cid)
    log_decision(event="place_stop_market", symbol=s, side=side, extra={"stop": stop_price, "qty": float(q) if q else None})
    return resp

def place_take_profit_safe(*, symbol: str, side: str, stop_price: float, qty: Optional[float] = None,
                           reduce_only=True, position_side=None, idp_key=None) -> Dict[str, Any]:
    s, side = symbol.upper().strip(), _coerce_side(side)
    q = None
    f = get_symbol_filters(s)
    if qty is not None:
        q, _, f = _quantize_price_qty(s, qty, None)
        _ensure_notional_ok(q, Decimal(stop_price), f)
    cid = _client_oid("TPM:", s, "tp")
    idp = idp_key or f"tp:{s}:{side}:{_fmt(stop_price)}:{_fmt(float(q) if q else 0)}"
    if not idp_claim(idp, _IDP_TTL): raise RuntimeError("duplicate take-profit order")
    resp = place_take_profit_market(symbol=s, side=side, stop_price=stop_price,
                                    quantity=(float(q) if q else None),
                                    reduce_only=reduce_only, position_side=position_side,
                                    new_client_order_id=cid)
    log_decision(event="place_tp_market", symbol=s, side=side, extra={"tp": stop_price, "qty": float(q) if q else None})
    return resp


