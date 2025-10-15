# utils/position_sizing.py
from __future__ import annotations

import os, json, math
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN, getcontext
from typing import Optional, Dict, Tuple
from contextlib import suppress

# High precision for tick/step math
getcontext().prec = 28

D = Decimal

# ---------- ENV helpers ----------
def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return default

def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default

# ---------- Quantization helpers (Decimal, step-aware) ----------
def _as_dec(x: float | int | str | Decimal) -> Decimal:
    if isinstance(x, Decimal):
        return x
    return D(str(x))

def _q_floor(value: Decimal, step: Decimal) -> Decimal:
    """
    Truncate down to the nearest multiple of `step` (LOT_SIZE style).
    """
    if step <= 0:
        return value
    # (value // step) * step — exact step truncation, no FP error
    return (value // step) * step

def _q_ceil(value: Decimal, step: Decimal) -> Decimal:
    """
    Round up to the nearest multiple of `step` (used for min-notional bump).
    """
    if step <= 0:
        return value
    # ceil division for Decimal steps: ((value + step - eps) // step) * step
    # but simpler: if divisible -> value, else floor + step
    floored = _q_floor(value, step)
    return floored if floored == value else (floored + step)

def _clamp_positive(x: Decimal, minimum: Decimal) -> Decimal:
    return x if x >= minimum else minimum

# ---------- Filters ----------
@dataclass(frozen=True)
class SymbolFilters:
    qty_step: Decimal
    price_tick: Decimal
    min_notional: Decimal

def _from_env_defaults() -> SymbolFilters:
    qty_step = _as_dec(_env_float("DEFAULT_QTY_STEP", 0.001))
    price_tick = _as_dec(_env_float("DEFAULT_PRICE_TICK", 0.01))
    min_notional = _as_dec(_env_float("MIN_NOTIONAL_USDT", 5.0))
    return SymbolFilters(qty_step=qty_step, price_tick=price_tick, min_notional=min_notional)

def _apply_symbol_overrides(sym: str, f: SymbolFilters) -> SymbolFilters:
    s = sym.upper()
    # Per-symbol overrides: QTY_STEP_OVERRIDE__BTCUSDT, PRICE_DP_OVERRIDE__BTCUSDT (as decimals), MIN_NOTIONAL_OVERRIDE__BTCUSDT
    with suppress(Exception):
        q_override = os.getenv(f"QTY_STEP_OVERRIDE__{s}")
        if q_override:
            f = SymbolFilters(qty_step=_as_dec(q_override), price_tick=f.price_tick, min_notional=f.min_notional)
    with suppress(Exception):
        # PRICE_DP_OVERRIDE maps decimal places; convert to tick like 10^-dp
        dp_override = os.getenv(f"PRICE_DP_OVERRIDE__{s}")
        if dp_override and str(dp_override).strip() != "":
            dp = int(dp_override)
            tick = D(1) / (D(10) ** dp)
            f = SymbolFilters(qty_step=f.qty_step, price_tick=tick, min_notional=f.min_notional)
    with suppress(Exception):
        mn_override = os.getenv(f"MIN_NOTIONAL_OVERRIDE__{s}")
        if mn_override:
            f = SymbolFilters(qty_step=f.qty_step, price_tick=f.price_tick, min_notional=_as_dec(mn_override))
    return f

def _symbol_filters_from_exchange(symbol: str) -> Optional[SymbolFilters]:
    """
    Try utils.exchange_info.get_symbol_filters(symbol) -> dict with keys like:
    stepSize/tickSize/minNotional (or snake_case)
    """
    with suppress(Exception):
        from utils.exchange_info import get_symbol_filters  # type: ignore
        f = get_symbol_filters(symbol)
        if not f:
            return None
        step = f.get("stepSize") or f.get("qty_step") or f.get("step_size")
        tick = f.get("tickSize") or f.get("price_tick") or f.get("tick_size")
        mn = f.get("minNotional") or f.get("min_notional")
        if step and tick and mn:
            return SymbolFilters(qty_step=_as_dec(step), price_tick=_as_dec(tick), min_notional=_as_dec(mn))
        # Partial info: fill from env defaults
        base = _from_env_defaults()
        return SymbolFilters(
            qty_step=_as_dec(step) if step else base.qty_step,
            price_tick=_as_dec(tick) if tick else base.price_tick,
            min_notional=_as_dec(mn) if mn else base.min_notional,
        )
    return None

def _symbol_filters(symbol: str) -> SymbolFilters:
    f = _symbol_filters_from_exchange(symbol) or _from_env_defaults()
    return _apply_symbol_overrides(symbol, f)

# ---------- Leverage cap ----------
def _leverage_cap(symbol: str, req_leverage: int) -> int:
    """
    קובע מינוף סופי לפי קאפים גלובליים/לסימבול.
    """
    max_lev = _env_int("MAX_LEVERAGE", 20)

    sym_cap = None
    caps_raw = os.getenv("LEVERAGE_SYMBOL_CAPS", "")
    if caps_raw:
        caps = None
        with suppress(Exception):
            caps = json.loads(caps_raw)
        if caps is None:
            with suppress(Exception):
                caps = json.loads(caps_raw.strip("'\""))
        if isinstance(caps, dict):
            with suppress(Exception):
                sym_cap = int(caps.get(symbol, max_lev))

    adx_cap = None
    adx_map_raw = os.getenv("LEV_ADX_MAP_JSON", "")
    if adx_map_raw:
        adx_map = None
        with suppress(Exception):
            adx_map = json.loads(adx_map_raw)
        if isinstance(adx_map, dict) and adx_map:
            with suppress(Exception):
                adx_cap = max(int(v) for v in adx_map.values())

    caps_to_apply = [int(req_leverage or 0), int(max_lev)]
    if sym_cap: caps_to_apply.append(int(sym_cap))
    if adx_cap: caps_to_apply.append(int(adx_cap))
    # keep within [1, ...]
    vals = [x for x in caps_to_apply if x and x > 0]
    return max(1, min(vals)) if vals else 1

# ---------- Public API ----------
def _compute_qty_by_budget(price_dec: Decimal, lev: int, budget_usdt: Decimal) -> Decimal:
    """
    raw_qty = (budget * lev) / price
    """
    if price_dec <= 0 or lev <= 0 or budget_usdt <= 0:
        return D(0)
    return (budget_usdt * D(lev)) / price_dec

def auto_qty(symbol: str, symbol_price: float, leverage: int) -> Optional[float]:
    """
    מחשב כמות לפי ENV:
      AUTO_QTY_ENABLE=1
      AUTO_QTY_BUDGET_USDT=100
      AUTO_QTY_MARGIN_BUFFER_PCT=0.20
    ומכבד:
      MAX_TRADE_BUDGET, DEFAULT_QTY_STEP, MIN_NOTIONAL_USDT
    """
    if os.getenv("AUTO_QTY_ENABLE", "0") != "1":
        return None

    budget = _as_dec(_env_float("AUTO_QTY_BUDGET_USDT", 50.0))
    buf    = _as_dec(_env_float("AUTO_QTY_MARGIN_BUFFER_PCT", 0.20))
    max_budget = _as_dec(_env_float("MAX_TRADE_BUDGET", float(budget)))

    budget = budget if budget <= max_budget else max_budget

    lev = _leverage_cap(symbol, int(leverage or 0))
    price = _as_dec(symbol_price)

    effective = budget * (D(1) - buf)
    if price <= 0 or lev <= 0 or effective <= 0:
        return None

    f = _symbol_filters(symbol)
    raw_qty = _compute_qty_by_budget(price, lev, effective)
    # floor to step for exchange acceptance
    qty = _q_floor(raw_qty, f.qty_step)

    # ensure min notional: ceil to step if needed
    if qty * price < f.min_notional:
        needed = f.min_notional / price
        qty = _q_ceil(needed, f.qty_step)

    return float(qty) if qty > 0 else None

def ensure_final_qty(ticket: dict, symbol_price: float) -> dict:
    """
    קובע leverage סופי לפי קאפים; ואם qty חסר/0 – מחשב לפי AUTO_QTY_*.
    Also enforces minNotional by bumping qty up to the next step if required.
    """
    symbol = (ticket.get("symbol") or "").upper()
    req_lev = int(ticket.get("leverage") or ticket.get("lev") or _env_int("MIN_LEVERAGE", 5))
    final_lev = _leverage_cap(symbol, req_lev)
    ticket["leverage"] = final_lev

    # Calculate or normalize qty
    q_raw = ticket.get("qty") or ticket.get("quantity")
    qf = float(q_raw) if q_raw is not None else 0.0
    price = _as_dec(symbol_price)
    f = _symbol_filters(symbol)

    if q_raw is None or qf <= 0.0:
        q_calc = auto_qty(symbol, float(price), int(final_lev))
        if q_calc and q_calc > 0:
            qty = _as_dec(q_calc)
        else:
            qty = D(0)
    else:
        qty = _as_dec(qf)

    # Quantize to step
    qty = _q_floor(qty, f.qty_step)

    # If still below minNotional, bump up to next step
    if qty > 0 and (qty * price) < f.min_notional:
        needed = f.min_notional / price
        qty = _q_ceil(needed, f.qty_step)

    # Final guard: qty must be >= 1 step
    if qty > 0 and qty < f.qty_step:
        qty = f.qty_step

    # Store back if positive
    if qty > 0:
        ticket["qty"] = float(qty)

    return ticket




