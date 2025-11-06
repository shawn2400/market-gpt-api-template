# utils/trade_manager.py
from __future__ import annotations

import os
import time
import math
import json
import logging
import asyncio
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from contextlib import suppress

import pandas as pd

from utils import ws_fallback
from utils.indicators import atr, macd, adx
from utils.binance_client import (
    get_open_positions,
    get_klines_df,
    close_all_positions,
    get_open_orders,
    futures_cancel_order,
    futures_mark_price,
    futures_create_order,
    get_symbol_filters,
)

# Guard (optional, safe if missing)
with suppress(Exception):
    from utils.guard_stop import ensure_protective_stop  # type: ignore

# AI Performance Tracking
with suppress(Exception):
    from utils.ai_tracker import log_outcome  # type: ignore

# Telegram notifications
with suppress(Exception):
    from utils.alerts import send_telegram_message  # type: ignore

# Dynamic Trading System (MetaBrain v8.0) - Legacy
with suppress(Exception):
    from utils.regime_glue import RegimeAdapter
    from utils.sl_manager import ZeroGapSLManager
    from utils.tp_ladder import TPLadder
    import utils.binance_client as _binance_client_module
    
    _regime_adapter = RegimeAdapter()
    _sl_manager = ZeroGapSLManager(_binance_client_module)
    _tp_ladder = TPLadder(_binance_client_module)
    _DYNAMIC_TRADING_AVAILABLE = True
except Exception as _e:
    _regime_adapter = None  # type: ignore
    _sl_manager = None  # type: ignore
    _tp_ladder = None  # type: ignore
    _DYNAMIC_TRADING_AVAILABLE = False

# Progressive Rollout System (v2 - Regime-based Dynamic Trading)
with suppress(Exception):
    from utils.regime_detector_v2 import detect_market_regime_v2
    from utils.adaptive_mixer import adaptive_mix
    from utils.precision import quantize_price, quantize_qty
    from utils.idempotency_simple import make_key, seen
    from utils.circuit_breaker import track as cb_track, allow as cb_allow
    from utils.metrics_dyn import (
        dyn_decisions, dyn_skips, dyn_errors, sl_changes, tp_sets,
        age_guard_hit, conf_low_hit, cb_blocks, live_enforce, regime_confidence
    )
    _PROGRESSIVE_ROLLOUT_AVAILABLE = True
except Exception as _e:
    logger.warning(f"[Progressive Rollout] Import failed: {_e}")
    _PROGRESSIVE_ROLLOUT_AVAILABLE = False

logger = logging.getLogger("algogpt.trade_manager")

# Enable real-time Telegram notifications for all management actions
TELEGRAM_NOTIFY_TRADES = os.getenv("TELEGRAM_SEND_ENABLE", "1").lower() in ("1", "true", "yes", "on")

# ──────────────────────────────────────────────────────────────────────────────
# ENV / Flags
# ──────────────────────────────────────────────────────────────────────────────
_COOLDOWN = int(os.getenv("TM_UPDATE_COOLDOWN_SEC", "30"))

# Breakeven guard
_BE_GUARD_ENABLE = os.getenv("BE_GUARD_ENABLE", "1").lower() in ("1", "true", "yes", "on")
_BE_GUARD_EVERY_SEC = int(os.getenv("BE_GUARD_EVERY_SEC", "30"))
_TP1_TAGS: List[str] = [t.strip() for t in os.getenv("TP1_TAGS", "TP1,tp1,tp_1,TAKE_PROFIT_1").split(",") if t.strip()]
TP_BE_ONLY_AFTER_TP1 = os.getenv("TP_BE_ONLY_AFTER_TP1", "1").lower() in ("1", "true", "yes", "on")
TP_BE_OFFSET_BPS = float(os.getenv("TP_BE_OFFSET_BPS", "5"))

ORDER_ID_PREFIX = os.getenv("ORDER_ID_PREFIX", "").strip()
CANCEL_ONLY_PREFIXED_ORDERS = os.getenv("CANCEL_ONLY_PREFIXED_ORDERS", "0").lower() in ("1", "true", "yes", "on")
CANCEL_PREFIX_OVERRIDE = os.getenv("CANCEL_PREFIX_OVERRIDE", "").strip()

SL_LIMIT_OFFSET_BPS = float(os.getenv("SL_LIMIT_OFFSET_BPS", "8"))
TP_LIMIT_OFFSET_BPS = float(os.getenv("TP_LIMIT_OFFSET_BPS", "8"))

_TRAIL_FREEZE_ENABLE = os.getenv("TRAIL_FREEZE_ENABLE", "0").lower() in ("1", "true", "yes", "on")
_TRAIL_FREEZE_MIN_SEC = int(os.getenv("TRAIL_FREEZE_MIN_SEC", "60"))
_TRAIL_FREEZE_MAX_SEC = int(os.getenv("TRAIL_FREEZE_MAX_SEC", "180"))
_TRAIL_FREEZE_SPIKE_ATR_MULT = float(os.getenv("TRAIL_FREEZE_SPIKE_ATR_MULT", "1.8"))
_TRAIL_FREEZE_ADX_WEAK = float(os.getenv("TRAIL_FREEZE_ADX_WEAK", "20"))
_last_trail_freeze_until: Dict[str, float] = {}

SL_BREATH_ALLOW = os.getenv("SL_BREATH_ALLOW", "1").lower() in ("1", "true", "yes", "on")
SL_BREATH_ATR_MULT = float(os.getenv("SL_BREATH_ATR_MULT", "1.0"))
LOCK_PROFIT_KEEP_RATIO = float(os.getenv("LOCK_PROFIT_KEEP_RATIO", "0.8"))
BREATH_COND_MIN_PROFIT_PCT = float(os.getenv("BREATH_COND_MIN_PROFIT_PCT", "0.8"))

DAILY_LOSS_CAP = float(os.getenv("DAILY_HARD_LOSS_USD", "-150"))
_daily_pnl = 0.0
_trades_today: List[dict] = []
_cap_triggered = False

_health_fails = 0
_HEALTH_FAIL_MAX = int(os.getenv("KILLSWITCH_THRESHOLD", "3"))

# ──────────────────────────────────────────────────────────────────────────────
# Progressive Rollout ENV (Shadow → Single Symbol → Full)
# ──────────────────────────────────────────────────────────────────────────────
MANAGER_DYN_PATH = os.getenv("MANAGER_DYN_PATH", "1") == "1"
DYN_SHADOW = os.getenv("DYN_SHADOW", "1") == "1"  # Phase 1: Shadow mode
DYN_ENFORCE = os.getenv("DYN_ENFORCE", "0") == "1"  # Phase 2+: Enforce mode
DYN_MIN_CONF = float(os.getenv("DYN_MIN_CONF", "0.62"))
DYN_SAFE_STALE_SEC = int(os.getenv("DYN_SAFE_STALE_SEC", "35"))
BTC_GATE_ENABLE = os.getenv("BTC_GATE_ENABLE", "1") == "1"

# Symbol whitelist/blacklist for Progressive Rollout
_ALLOWED = {s.strip().upper() for s in os.getenv("DYN_ALLOWED_SYMBOLS", "").split(",") if s.strip()}
_DENY = {s.strip().upper() for s in os.getenv("DYN_DENYLIST", "").split(",") if s.strip()}

def _enforce_allowed(sym: str) -> bool:
    """Check if symbol is allowed for dynamic enforce mode."""
    su = (sym or "").upper()
    if su in _DENY:
        return False
    if _ALLOWED:
        return su in _ALLOWED
    return True  # If no whitelist, allow all

# Set metrics gauge for enforce status
if _PROGRESSIVE_ROLLOUT_AVAILABLE:
    try:
        live_enforce.set(1.0 if (DYN_ENFORCE and not DYN_SHADOW) else 0.0)
    except Exception:
        pass

REVIEW_PATH = Path("static/cache/trade_reviews.json")

try:
    from utils.ops_guard import ops_tick
except Exception:
    async def ops_tick(**kwargs):  # type: ignore
        return None

try:
    get_price_age = ws_fallback.get_price_age  # type: ignore
except Exception:
    def get_price_age(symbol: str):  # type: ignore
        return None

try:
    from utils.config import ALLOW_MANAGE_OPEN_TRADES, AUTO_RUN  # noqa: F401
except Exception:
    ALLOW_MANAGE_OPEN_TRADES, AUTO_RUN = True, True  # safe defaults

from utils.telegram_notifier import (
    notify_sl_tp_update,
    notify_info,
    notify_error,
    notify_heartbeat,
    notify_daily_summary,
)

DEFAULT_QTY_STEP = float(os.getenv("DEFAULT_QTY_STEP", "0.001"))
DEFAULT_TICK = float(os.getenv("DEFAULT_PRICE_TICK", "0.01"))

def _decimals(step_str: str) -> int:
    if "." not in step_str:
        return 0
    return len(step_str.split(".")[1].rstrip("0"))

def _filters(symbol: str) -> Dict[str, Any]:
    return get_symbol_filters(symbol) or {}

def _q_price(symbol: str, price: float) -> Tuple[str, float]:
    f = _filters(symbol)
    tick = float(f.get("tickSize") or DEFAULT_TICK) or DEFAULT_TICK
    decs = _decimals(str(f.get("tickSize") or DEFAULT_TICK))
    steps = round(price / tick)
    p = steps * tick
    s = f"{p:.{decs}f}"
    return s, float(s)

def _q_qty(symbol: str, qty: float) -> Tuple[str, float]:
    f = _filters(symbol)
    step = float(f.get("stepSize") or DEFAULT_QTY_STEP) or DEFAULT_QTY_STEP
    decs = _decimals(str(f.get("stepSize") or DEFAULT_QTY_STEP))
    steps = math.floor(max(0.0, qty) / step)
    q = max(step, steps * step)
    s = f"{q:.{decs}f}"
    return s, float(s)

def _offset_bps(base: float, bps: float, sign: int) -> float:
    return base * (1.0 + sign * (bps / 10000.0))

def _cancel_closing_orders(symbol: str, types: Tuple[str, ...], position_side: Optional[str] = None) -> int:
    """Cancel closing orders for a symbol, optionally filtered by positionSide for Hedge Mode."""
    try:
        orders = get_open_orders(symbol) or []
    except Exception:
        return 0
    pref = (CANCEL_PREFIX_OVERRIDE or ORDER_ID_PREFIX or "").strip()
    only_pref = CANCEL_ONLY_PREFIXED_ORDERS and bool(pref)
    tset = {t.upper() for t in types}
    count = 0
    for o in orders:
        st = (o.get("status") or "").upper()
        if st not in ("NEW", "PARTIALLY_FILLED"):
            continue
        typ = (o.get("type") or o.get("origType") or "").upper()
        if typ not in tset:
            continue
        # CRITICAL: In Hedge Mode, only cancel orders matching this position side
        if position_side:
            order_pos_side = (o.get("positionSide") or "").upper()
            if order_pos_side and order_pos_side != position_side.upper():
                continue
        if only_pref:
            coid = str(o.get("clientOrderId") or o.get("origClientOrderId") or "")
            if not coid.startswith(pref):
                continue
        oid = o.get("orderId")
        if oid is None:
            continue
        try:
            futures_cancel_order(symbol, oid)
            count += 1
        except Exception as e:
            logger.warning("[tm.cancel] cancel failed %s/%s: %s", symbol, oid, e)
    return count

def _current_stop(symbol: str, side: str) -> Optional[float]:
    try:
        orders = get_open_orders(symbol) or []
    except Exception:
        return None
    stops = []
    for o in orders:
        typ = (o.get("type") or "").upper()
        if "STOP" not in typ:
            continue
        sp = float(o.get("stopPrice") or o.get("price") or 0.0)
        if sp > 0:
            stops.append(sp)
    if not stops:
        return None
    return max(stops) if side.upper() == "LONG" else min(stops)

def modify_stop_loss(symbol: str, new_price: float, *, position_side: str = "LONG", qty_hint: Optional[float] = None) -> Dict[str, Any]:
    sym = symbol.upper()
    close_side = "SELL" if position_side.upper() == "LONG" else "BUY"
    
    print(f"📍 [modify_stop_loss] {sym} {position_side}: Attempting to set SL @ {new_price:.4f}")
    logger.info(f"[modify_stop_loss] {sym} {position_side} - target SL: {new_price}")
    
    # CRITICAL: In Hedge Mode, only cancel orders matching this position side
    cancelled = _cancel_closing_orders(sym, ("STOP", "STOP_MARKET"), position_side=position_side)
    if cancelled > 0:
        print(f"🗑️ [modify_stop_loss] Cancelled {cancelled} existing {position_side} SL orders for {sym}")
        logger.info(f"[modify_stop_loss] Cancelled {cancelled} existing {position_side} SL orders")
    
    stop_str, _ = _q_price(sym, float(new_price))
    qty = qty_hint
    if not qty or qty <= 0:
        # CRITICAL: Filter positions by positionSide in Hedge Mode
        try:
            for p in get_open_positions(sym):
                pos_side = (p.get("positionSide") or "BOTH").upper()
                amt = float(p.get("positionAmt") or 0.0)
                # Match position side (or use BOTH for One-way mode)
                if pos_side == position_side.upper() or pos_side == "BOTH":
                    if abs(amt) > 0:
                        qty = abs(amt)
                        break
        except Exception:
            pass
    if not qty or qty <= 0:
        print(f"❌ [modify_stop_loss] {sym} {position_side} - FAILED: No position quantity found")
        logger.error(f"[modify_stop_loss] {sym} {position_side} - qty missing")
        return {"ok": False, "error": "qty_missing_for_modify_sl"}
    
    qty_str, _ = _q_qty(sym, float(qty))
    print(f"🎯 [modify_stop_loss] {sym} placing {close_side} STOP_MARKET: qty={qty_str}, stopPrice={stop_str}, positionSide={position_side}")
    
    try:
        resp = futures_create_order(
            symbol=sym,
            side=close_side,
            type="STOP_MARKET",
            positionSide=position_side.upper(),  # CRITICAL: Hedge Mode requires this!
            # reduceOnly NOT needed in Hedge Mode (implicit from positionSide)
            stopPrice=stop_str,
            quantity=qty_str,
            workingType="MARK_PRICE",
            timeInForce="GTC",
        )
        order_id = resp.get("orderId", "unknown")
        print(f"✅ [modify_stop_loss] {sym} SL placed successfully! OrderID: {order_id}")
        logger.info(f"[modify_stop_loss] {sym} SL order created: {order_id}")
        return {"ok": True, "response": resp}
    except Exception as e:
        print(f"❌ [modify_stop_loss] {sym} placement FAILED: {e}")
        logger.error(f"[modify_stop_loss] {sym} failed: {e}")
        return {"ok": False, "error": str(e)}

def modify_take_profit(symbol: str, new_price: float, *, position_side: str = "LONG", qty_hint: Optional[float] = None) -> Dict[str, Any]:
    sym = symbol.upper()
    close_side = "SELL" if position_side.upper() == "LONG" else "BUY"
    
    # CRITICAL: In Hedge Mode, only cancel orders matching this position side
    _cancel_closing_orders(sym, ("TAKE_PROFIT", "TAKE_PROFIT_MARKET"), position_side=position_side)
    
    stop_str, stop_px = _q_price(sym, float(new_price))
    limit_px = _offset_bps(stop_px, TP_LIMIT_OFFSET_BPS, +1 if close_side == "SELL" else -1)
    price_str, _ = _q_price(sym, float(limit_px))
    qty = qty_hint
    if not qty or qty <= 0:
        # CRITICAL: Filter positions by positionSide in Hedge Mode
        try:
            for p in get_open_positions(sym):
                pos_side = (p.get("positionSide") or "BOTH").upper()
                amt = float(p.get("positionAmt") or 0.0)
                # Match position side (or use BOTH for One-way mode)
                if pos_side == position_side.upper() or pos_side == "BOTH":
                    if abs(amt) > 0:
                        qty = abs(amt)
                        break
        except Exception:
            pass
    if not qty or qty <= 0:
        return {"ok": False, "error": "qty_missing_for_modify_tp"}
    qty_str, _ = _q_qty(sym, float(qty))
    try:
        resp = futures_create_order(
            symbol=sym,
            side=close_side,
            type="TAKE_PROFIT",
            positionSide=position_side.upper(),  # CRITICAL: Hedge Mode requires this!
            # reduceOnly NOT needed in Hedge Mode (implicit from positionSide)
            stopPrice=stop_str,
            price=price_str,
            quantity=qty_str,
            timeInForce="GTC",
            workingType="MARK_PRICE",
        )
        return {"ok": True, "response": resp}
    except Exception as e:
        return {"ok": False, "error": str(e)}

try:
    from utils.binance_client import set_breakeven_stop as _set_be_native  # type: ignore
except Exception:
    _set_be_native = None  # type: ignore

_last_update: Dict[str, float] = {}
_last_be_guard = 0.0
_be_set_once: set[str] = set()
_prev_open_positions: Dict[str, Dict[str, Any]] = {}

def _tp1_pct_default() -> float:
    csv = os.getenv("LADDER_TP_DEFAULT_PCTS", "1.8,3.2,5.5")
    try:
        arr = [float(x) for x in csv.split(",") if x.strip()]
        return min(arr) if arr else 1.8
    except Exception:
        return 1.8

def _price_now(symbol: str) -> float:
    try:
        px = ws_fallback.get_price(symbol)
        if px:
            return float(px)
    except Exception:
        pass
    try:
        px2 = futures_mark_price(symbol)
        if px2:
            return float(px2)
    except Exception:
        pass
    return 0.0

def _is_finite_number(x: Any) -> bool:
    try:
        xf = float(x)
        return math.isfinite(xf)
    except Exception:
        return False

async def _detect_closures_and_review(curr_positions: List[Dict[str, Any]]) -> None:
    global _prev_open_positions
    try:
        curr_open: Dict[str, Dict[str, Any]] = {}
        for p in curr_positions or []:
            try:
                sym = (p.get("symbol") or "").upper()
                amt = float(p.get("positionAmt") or 0.0)
                if sym and abs(amt) > 0:
                    curr_open[sym] = p
            except Exception:
                continue

        closed_syms = [s for s in _prev_open_positions.keys() if s not in curr_open]
        if closed_syms:
            try:
                from utils.ai_reviewer import review_trade_async
            except Exception as e:
                logger.debug("[ai_review] module missing, skip: %s", e)
                _prev_open_positions = curr_open
                return

            for s in closed_syms:
                prev = _prev_open_positions.get(s, {}) or {}
                entry = float(prev.get("entryPrice") or 0.0) or 0.0
                side = "LONG" if float(prev.get("positionAmt") or 0) > 0 else "SHORT"
                exit_px = _price_now(s) or entry
                
                # 📊 AI PERFORMANCE TRACKING: Log trade outcome
                try:
                    # Calculate P&L
                    qty = abs(float(prev.get("positionAmt") or 0.0))
                    if side == "LONG":
                        pnl_usd = (exit_px - entry) * qty
                        pnl_pct = ((exit_px / entry) - 1.0) * 100.0
                    else:
                        pnl_usd = (entry - exit_px) * qty
                        pnl_pct = ((entry / exit_px) - 1.0) * 100.0
                    
                    # Determine exit reason and success
                    was_successful = pnl_usd > 0
                    if was_successful:
                        exit_reason = "tp"  # Assume TP if profitable
                    else:
                        exit_reason = "sl"  # Assume SL if not profitable
                    
                    # Calculate RR achieved (approximate based on P&L %)
                    # Assuming standard risk of ~2%, RR = profit% / 2%
                    rr_achieved = abs(pnl_pct) / 2.0 if abs(pnl_pct) > 0 else 0.0
                    
                    # Calculate time in trade (if we have updateTime)
                    time_in_trade_minutes = 0
                    try:
                        update_time = prev.get("updateTime", 0)
                        if update_time > 0:
                            time_in_trade_minutes = int((time.time() * 1000 - update_time) / 60000)
                    except:
                        pass
                    
                    # Try to get prediction_id from trade metadata
                    # For now, we'll construct it from symbol and approximate timestamp
                    # This is a workaround - ideally prediction_id should be stored in trade metadata
                    prediction_id = prev.get("prediction_id", "")
                    if not prediction_id:
                        # Fallback: try to match based on symbol and recent time
                        # This won't link to specific predictions but allows outcome logging
                        logger.debug(f"[ai_outcome] No prediction_id found for {s}, outcome not linked")
                    else:
                        # Log outcome with ai_tracker
                        if log_outcome:
                            success = log_outcome(
                                prediction_id=prediction_id,
                                symbol=s,
                                pnl_usd=pnl_usd,
                                pnl_pct=pnl_pct,
                                rr_achieved=rr_achieved,
                                time_in_trade_minutes=max(1, time_in_trade_minutes),
                                exit_reason=exit_reason,
                                was_successful=was_successful
                            )
                            if success:
                                logger.info(f"✅ Logged AI outcome for {s}: P&L=${pnl_usd:.2f}, RR={rr_achieved:.2f}")
                except Exception as e:
                    logger.warning(f"[ai_outcome] Failed to log outcome for {s}: {e}")
                
                # Continue with AI review
                ctx = {"entry": entry, "exit": exit_px, "pnl_usd": pnl_usd if 'pnl_usd' in locals() else None, "rr": None, "indicators": {}, "reasons": ["auto_detected_closure"]}
                try:
                    await review_trade_async(s, side, ctx, to_telegram=True)
                except Exception as e:
                    logger.warning("[ai_review] failed for %s: %s", s, e)

        _prev_open_positions = curr_open
    except Exception as e:
        logger.debug("[ai_review] closure detect error: %s", e)

def _maybe_freeze_trailing(symbol: str, df: pd.DataFrame, atr_now: float, adx_now: float, macd_diff_now: float) -> bool:
    if not _TRAIL_FREEZE_ENABLE:
        return False
    now = time.time()
    t_until = _last_trail_freeze_until.get(symbol, 0.0)
    if now < t_until:
        return True
    try:
        last_high = float(df["high"].iloc[-1])
        last_low = float(df["low"].iloc[-1])
    except Exception:
        return False
    last_range = abs(last_high - last_low)
    if atr_now <= 0 or not math.isfinite(atr_now) or not math.isfinite(last_range):
        return False
    spike_mult = last_range / float(atr_now)
    if spike_mult >= _TRAIL_FREEZE_SPIKE_ATR_MULT:
        base = _TRAIL_FREEZE_MIN_SEC + int((spike_mult - 1.0) * 30)
        if adx_now < _TRAIL_FREEZE_ADX_WEAK:
            base = int(base * 1.25)
        if abs(macd_diff_now) > 0.5:
            base += 20
        dur = max(_TRAIL_FREEZE_MIN_SEC, min(_TRAIL_FREEZE_MAX_SEC, base))
        _last_trail_freeze_until[symbol] = now + dur
        logger.info({"event": "trail_freeze","symbol": symbol,"dur_sec": dur,"spike_mult": round(spike_mult, 2),"adx": round(adx_now, 1),"macd_delta": round(macd_diff_now, 2)})
        return True
    return False

async def manage_open_trades():
    global _daily_pnl, _cap_triggered
    if not ALLOW_MANAGE_OPEN_TRADES or _cap_triggered:
        print(f"⚠️ [manage_open_trades] BLOCKED: ALLOW_MANAGE={ALLOW_MANAGE_OPEN_TRADES}, cap_triggered={_cap_triggered}")
        logger.info(f"[manage] Disabled or cap triggered, skipping (ALLOW={ALLOW_MANAGE_OPEN_TRADES}, cap={_cap_triggered})")
        return

    try:
        positions = get_open_positions() or []
        print(f"📊 [manage_open_trades] Found {len(positions)} open positions")
        logger.info(f"[manage] Found {len(positions)} open positions")
        now = time.time()
        for pos in positions:
            try:
                sym = (pos.get("symbol") or "").upper()
                qty = float(pos.get("positionAmt") or 0)
                entry = float(pos.get("entryPrice") or 0)
                print(f"🔍 [manage] Processing {sym}: qty={qty}, entry={entry}")
                logger.info(f"[manage] Processing {sym}: qty={qty}, entry={entry}")
                if not sym or entry <= 0 or abs(qty) <= 0:
                    print(f"❌ [manage] Skipping {sym}: invalid data (qty={qty}, entry={entry})")
                    logger.info(f"[manage] Skipping {sym}: invalid data (qty={qty}, entry={entry})")
                    continue
                side = "LONG" if qty > 0 else "SHORT"
                price = _price_now(sym)
                if price <= 0:
                    print(f"❌ [manage] Skipping {sym}: no price")
                    logger.info(f"[manage] Skipping {sym}: no price")
                    continue

                if now - _last_update.get(sym, 0) < _COOLDOWN:
                    print(f"⏭️ [manage] Skipping {sym}: cooldown active ({_COOLDOWN}s)")
                    logger.info(f"[manage] Skipping {sym}: cooldown active")
                    continue

                df = get_klines_df(sym, interval="5m", limit=50)
                if df is None or getattr(df, "empty", False):
                    print(f"❌ [manage] Skipping {sym}: failed to get klines data")
                    logger.info(f"[manage] Skipping {sym}: failed to get klines data")
                    continue

                atr_series = atr(df)
                adx_series = adx(df)
                current_atr = float(atr_series.iloc[-1]) if hasattr(atr_series, "iloc") else float(atr_series[-1])
                current_adx = float(adx_series.iloc[-1]) if hasattr(adx_series, "iloc") else float(adx_series[-1])
                macd_line, macd_signal, _ = macd(df["close"])
                macd_now = float(macd_line.iloc[-1] - macd_signal.iloc[-1])

                if not (_is_finite_number(current_atr) and current_atr > 0):
                    print(f"❌ [manage] Skipping {sym}: invalid ATR (atr={current_atr})")
                    logger.info(f"[manage] Skipping {sym}: invalid ATR")
                    continue
                if not _is_finite_number(current_adx):
                    print(f"❌ [manage] Skipping {sym}: invalid ADX (adx={current_adx})")
                    logger.info(f"[manage] Skipping {sym}: invalid ADX")
                    continue
                if not _is_finite_number(macd_now):
                    print(f"❌ [manage] Skipping {sym}: invalid MACD (macd={macd_now})")
                    logger.info(f"[manage] Skipping {sym}: invalid MACD")
                    continue

                # ═══════════════════════════════════════════════════════════════════
                # PROGRESSIVE ROLLOUT: Dynamic Regime-Based Management
                # ═══════════════════════════════════════════════════════════════════
                if MANAGER_DYN_PATH and _PROGRESSIVE_ROLLOUT_AVAILABLE:
                    try:
                        # Calculate RSI and ATR% for regime detection
                        try:
                            delta = df["close"].diff()
                            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
                            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
                            rs = gain / loss
                            rsi_series = 100 - (100 / (1 + rs))
                            current_rsi = float(rsi_series.iloc[-1])
                        except Exception:
                            current_rsi = 50.0  # Neutral fallback
                        
                        atr_pct = (current_atr / price) * 100.0 if price > 0 else 0.0
                        
                        # Calculate MACD slope (simple momentum)
                        try:
                            macd_slope = float(macd_line.iloc[-1] - macd_line.iloc[-5]) if len(macd_line) >= 5 else 0.0
                        except Exception:
                            macd_slope = 0.0
                        
                        # Get symbol filters for precision
                        filters = get_symbol_filters(sym) or {}
                        tick_size = float(filters.get("tickSize", 0.01))
                        step_size = float(filters.get("stepSize", 0.001))
                        
                        # Build Context object
                        context = {
                            "symbol": sym,
                            "side": side,
                            "entry_price": entry,
                            "atr": current_atr,
                            "atr_pct": atr_pct,
                            "adx": current_adx,
                            "macd_slope": macd_slope,
                            "rsi": current_rsi,
                            "tick_size": tick_size,
                            "step_size": step_size,
                            "position_qty": qty,
                            "last_market_update_ts": now,
                            "price": price,
                            "btc_gate_ok": True,  # TODO: Add real BTC correlation check if needed
                            "pnl_state": "normal",  # TODO: Track PnL state
                            "time_in_position_min": 0.0  # TODO: Track position age
                        }
                        
                        # Safety guards
                        required = ["symbol", "side", "entry_price", "atr", "atr_pct", "adx",
                                    "macd_slope", "rsi", "tick_size", "step_size", "position_qty", "last_market_update_ts"]
                        
                        if any(k not in context for k in required):
                            dyn_skips.labels(reason="missing_context").inc()
                            print(f"⚠️ [DynPath] {sym} missing context fields, skipping")
                        elif (now - float(context["last_market_update_ts"])) > DYN_SAFE_STALE_SEC:
                            age_guard_hit.inc()
                            dyn_skips.labels(reason="stale_data").inc()
                            print(f"⚠️ [DynPath] {sym} stale data ({now - context['last_market_update_ts']:.0f}s), skipping")
                        elif BTC_GATE_ENABLE and not bool(context.get("btc_gate_ok", True)):
                            dyn_skips.labels(reason="btc_gate").inc()
                            print(f"⚠️ [DynPath] {sym} BTC gate check failed, skipping")
                        elif not cb_allow():
                            cb_blocks.inc()
                            dyn_skips.labels(reason="circuit_block").inc()
                            print(f"⛔ [DynPath] Circuit breaker open, skipping all dynamic updates")
                        else:
                            # Detect regime
                            feats = {
                                "atr_pct": float(context["atr_pct"]),
                                "adx": float(context["adx"]),
                                "macd_slope": float(context["macd_slope"]),
                                "rsi": float(context["rsi"]),
                            }
                            r = detect_market_regime_v2(feats)
                            
                            if r.confidence < DYN_MIN_CONF:
                                conf_low_hit.inc()
                                dyn_skips.labels(reason="low_conf").inc()
                                print(f"⚠️ [DynPath] {sym} low confidence ({r.confidence:.3f} < {DYN_MIN_CONF}), skipping")
                            else:
                                # Adaptive parameter mixing
                                mix = adaptive_mix(
                                    regime=r.regime,
                                    confidence=r.confidence,
                                    atr_pct=feats["atr_pct"],
                                    pnl_state=context.get("pnl_state", "normal"),
                                    time_in_pos_min=context.get("time_in_position_min", 0.0)
                                )
                                
                                # Calculate SL/TP
                                sl_dist = mix["sl_atr"] * current_atr
                                if side == "LONG":
                                    sl_p = entry - sl_dist
                                else:
                                    sl_p = entry + sl_dist
                                
                                rr = mix["tp_rr"]
                                if side == "LONG":
                                    tp_p = entry + (rr * sl_dist)
                                else:
                                    tp_p = entry - (rr * sl_dist)
                                
                                # Quantize
                                qtz = quantize_qty(abs(float(context["position_qty"])), step_size)
                                sl_p = quantize_price(sl_p, tick_size)
                                tp_p = quantize_price(tp_p, tick_size)
                                
                                # Idempotency check
                                payload = json.dumps({
                                    "sym": context["symbol"],
                                    "sl": sl_p,
                                    "tp": tp_p,
                                    "qty": qtz,
                                    "side": side,
                                    "reg": r.regime,
                                    "conf": round(r.confidence, 3)
                                })
                                idem_key = make_key("manage_dyn", payload)
                                
                                if seen(idem_key):
                                    dyn_skips.labels(reason="idem_dup").inc()
                                    print(f"⏭️ [DynPath] {sym} duplicate detected (idempotency), skipping")
                                else:
                                    # Progressive rollout: check if symbol is allowed for enforce
                                    enforce_now = (DYN_ENFORCE and not DYN_SHADOW and _enforce_allowed(context["symbol"]))
                                    
                                    if not enforce_now:
                                        # SHADOW MODE
                                        dyn_decisions.labels(symbol=context["symbol"], regime=r.regime).inc()
                                        regime_confidence.labels(symbol=sym, regime=r.regime).set(r.confidence)
                                        print(json.dumps({
                                            "evt": "dyn_shadow",
                                            "sym": context["symbol"],
                                            "regime": r.regime,
                                            "conf": round(r.confidence, 3),
                                            "sl_atr": round(mix["sl_atr"], 3),
                                            "tp_rr": round(mix["tp_rr"], 3),
                                            "side": side,
                                            "sl_p": sl_p,
                                            "tp_p": tp_p,
                                            "qty": qtz
                                        }, ensure_ascii=False))
                                        cb_track(ok=True)
                                    else:
                                        # ENFORCE MODE
                                        print(f"🚀 [DynPath ENFORCE] {sym} {r.regime} (conf={r.confidence:.3f}) → SL={sl_p:.4f}, TP={tp_p:.4f}")
                                        
                                        # Execute Zero-Gap SL update
                                        ok1 = _sl_manager.safe_replace_sl(
                                            symbol=context["symbol"],
                                            new_stop_price=sl_p,
                                            qty=qtz,
                                            side=side
                                        )
                                        if ok1:
                                            sl_changes.labels(symbol=context["symbol"]).inc()
                                            print(f"✅ [DynPath] {sym} SL updated to {sl_p:.4f}")
                                        
                                        # Execute TP Ladder
                                        tp_ladder_levels = mix.get("tp_ladder", [tp_p])
                                        # Convert multipliers to actual prices
                                        tp_prices = []
                                        for mult in tp_ladder_levels:
                                            if side == "LONG":
                                                tp_level = entry + (sl_dist * mult)
                                            else:
                                                tp_level = entry - (sl_dist * mult)
                                            tp_prices.append(quantize_price(tp_level, tick_size))
                                        
                                        ok2 = _tp_ladder.set_tp_ladder(
                                            context["symbol"],
                                            entry,
                                            qtz,
                                            side,
                                            tp_prices
                                        )
                                        if ok2:
                                            tp_sets.labels(symbol=context["symbol"]).inc()
                                            print(f"✅ [DynPath] {sym} TP ladder set: {tp_prices}")
                                        
                                        dyn_decisions.labels(symbol=context["symbol"], regime=r.regime).inc()
                                        regime_confidence.labels(symbol=sym, regime=r.regime).set(r.confidence)
                                        cb_track(ok=(ok1 and ok2))
                                        
                                        # Skip legacy path if enforce successful
                                        if ok1 and ok2:
                                            _last_update[sym] = now
                                            print(f"✅ [DynPath] {sym} dynamic management complete, skipping legacy")
                                            continue
                    
                    except Exception as e:
                        dyn_errors.labels(stage="manage_dyn").inc()
                        cb_track(ok=False)
                        print(json.dumps({"evt": "dyn_error", "err": str(e), "sym": sym}, ensure_ascii=False))
                        logger.error(f"[DynPath] Error for {sym}: {e}", exc_info=True)
                
                # ═══════════════════════════════════════════════════════════════════
                # LEGACY PATH (Fallback if dynamic path skipped/failed)
                # ═══════════════════════════════════════════════════════════════════
                profit_pct = abs((price - entry) / entry) * 100.0

                be_trigger = float(os.getenv("TM_BE_MIN_PROFIT_PCT", "1.5"))
                if (profit_pct >= be_trigger) and (macd_now > 0 or current_adx > 20):
                    if not TP_BE_ONLY_AFTER_TP1:
                        if _set_be_native:
                            try:
                                _ = _set_be_native(sym, offset_bps=TP_BE_OFFSET_BPS)
                                await notify_sl_tp_update(sym, side, "breakeven", f"entry±{TP_BE_OFFSET_BPS}bps")
                            except Exception as e:
                                logger.error("[manage] native BE failed: %s", e)
                        else:
                            try:
                                modify_stop_loss(sym, entry, position_side=side)
                                await notify_sl_tp_update(sym, side, "breakeven", entry)
                            except Exception as e:
                                logger.error("[manage] BE fallback failed: %s", e)

                if _maybe_freeze_trailing(sym, df, current_atr, current_adx, macd_now):
                    _last_update[sym] = now
                    with suppress(Exception):
                        ensure_protective_stop(sym, prefer_mode="native")
                    continue

                try:
                    if side == "LONG":
                        recent_low = float(df["low"].iloc[-3:].min())
                        baseline_sl = recent_low - 0.6 * current_atr
                    else:
                        recent_high = float(df["high"].iloc[-3:].max())
                        baseline_sl = recent_high + 0.6 * current_atr
                except Exception as e:
                    logger.error("[manage] baseline build failed for %s: %s", sym, e)
                    _last_update[sym] = now
                    with suppress(Exception):
                        ensure_protective_stop(sym, prefer_mode="native")
                    continue

                target_sl = baseline_sl
                try:
                    if SL_BREATH_ALLOW and profit_pct >= BREATH_COND_MIN_PROFIT_PCT:
                        if side == "LONG":
                            keep_floor = entry + LOCK_PROFIT_KEEP_RATIO * max(0.0, price - entry)
                            relax = price - SL_BREATH_ATR_MULT * current_atr
                            target_sl = min(baseline_sl, relax)
                            target_sl = max(target_sl, keep_floor)
                        else:
                            keep_ceiling = entry - LOCK_PROFIT_KEEP_RATIO * max(0.0, entry - price)
                            relax = price + SL_BREATH_ATR_MULT * current_atr
                            target_sl = max(baseline_sl, relax)
                            target_sl = min(target_sl, keep_ceiling)
                        if (macd_now < 0 and current_adx >= 22):
                            if side == "LONG":
                                target_sl = min(target_sl, price - 1.2 * SL_BREATH_ATR_MULT * current_atr)
                                target_sl = max(target_sl, keep_floor)
                            else:
                                target_sl = max(target_sl, price + 1.2 * SL_BREATH_ATR_MULT * current_atr)
                                target_sl = min(target_sl, keep_ceiling)
                except Exception as e:
                    logger.debug("[manage] breathing compute failed %s: %s", sym, e)

                cur_stop = _current_stop(sym, side)
                
                # אם אין SL כלל - הגדר אחד מיד
                initial_sl_set = False
                if cur_stop is None or not _is_finite_number(cur_stop):
                    print(f"🚨 [manage] {sym} has NO protective SL - setting initial stop at {target_sl:.4f}")
                    logger.info(f"[manage] {sym} missing SL - setting initial stop")
                    try:
                        result = modify_stop_loss(sym, target_sl, position_side=side)
                        if result.get("ok"):
                            print(f"✅ [manage] {sym} initial SL placement confirmed by Binance")
                            await notify_sl_tp_update(sym, side, "initial_sl", target_sl)
                            cur_stop = target_sl
                            initial_sl_set = True  # דגל שהוגדר כעת
                        else:
                            error = result.get("error", "unknown")
                            print(f"❌ [manage] {sym} initial SL placement REJECTED by Binance: {error}")
                            logger.error(f"[manage] {sym} SL placement rejected: {error}")
                            cur_stop = entry  # fallback
                    except Exception as e:
                        logger.error("[manage] initial SL placement failed for %s: %s", sym, e)
                        cur_stop = entry  # fallback
                
                # שמירה על SL מעל entry אם כבר ב-BE
                if side == "LONG":
                    if (cur_stop >= entry) and (target_sl < entry):
                        target_sl = max(entry, target_sl)
                else:
                    if (cur_stop <= entry) and (target_sl > entry):
                        target_sl = min(entry, target_sl)

                # דלג על trailing update אם זה זה עתה הוגדר initial SL
                if not initial_sl_set:
                    try:
                        if _is_finite_number(target_sl) and _is_finite_number(cur_stop):
                            thresh = 0.25 * current_atr
                            need_update = (abs(target_sl - float(cur_stop)) >= thresh)
                            if need_update:
                                print(f"🔄 [manage] {sym} trailing SL: {cur_stop:.4f} → {target_sl:.4f} (Δ={abs(target_sl-cur_stop):.4f}, thresh={thresh:.4f})")
                                logger.info(f"[manage] {sym} trailing SL update: {cur_stop} → {target_sl}")
                                modify_stop_loss(sym, target_sl, position_side=side)
                                await notify_sl_tp_update(sym, side, "trailing", target_sl)
                            else:
                                print(f"⏭️ [manage] {sym} SL delta too small (Δ={abs(target_sl-cur_stop):.4f} < {thresh:.4f}), skipping update")
                    except Exception as e:
                        logger.error("[manage] trailing update failed for %s: %s", sym, e)
                else:
                    print(f"✅ [manage] {sym} initial SL successfully placed, skipping trailing logic this cycle")

                try:
                    if current_adx > 25 and macd_now > 0:
                        new_tp = (price + 4.5 * current_atr) if side == "LONG" else (price - 4.5 * current_atr)
                        if _is_finite_number(new_tp):
                            modify_take_profit(sym, new_tp, position_side=side)
                            await notify_sl_tp_update(sym, side, "tp", new_tp)
                except Exception as e:
                    logger.error("[manage] TP update failed for %s: %s", sym, e)

                # חוק-על: ודא SL מגן פעיל ואטומי
                with suppress(Exception):
                    ensure_protective_stop(sym, prefer_mode="native")

                _last_update[sym] = now

            except Exception as ie:
                logger.error("[manage] per-position error %s: %s", pos.get("symbol"), ie)

        if _BE_GUARD_ENABLE:
            await _be_guard_tick()

        await _detect_closures_and_review(positions)

        try:
            ttl = get_price_age("BTCUSDT")
            await ops_tick(price_ttl_sec=float(ttl) if ttl is not None else None)
        except Exception:
            pass

        if _daily_pnl <= DAILY_LOSS_CAP and not _cap_triggered:
            _cap_triggered = True
            await panic_close_all()
            await notify_error(f"🚨 Daily loss cap hit ({_daily_pnl:.2f} USDT) → AUTO_RUN disabled")
            os.environ["AUTO_RUN"] = "0"

    except Exception as e:
        logger.error(f"[manage] Error: {e}")
        await notify_error(f"⚠️ TradeManager Error: {e}")

async def manage_open_trades_loop(interval: int = 20):
    while True:
        await manage_open_trades()
        await asyncio.sleep(interval)

async def daily_summary():
    try:
        summary = {"pnl": _daily_pnl, "trades": _trades_today, "time": time.strftime("%d/%m/%Y %H:%M")}
        Path("static/cache").mkdir(parents=True, exist_ok=True)
        with open(Path("static/cache/trade_reviews.json"), "a", encoding="utf-8") as f:
            f.write(json.dumps(summary, ensure_ascii=False) + "\n")
        await notify_daily_summary(summary)
    except Exception as e:
        await notify_error(f"Daily summary failed: {e}")

async def heartbeat_loop(interval: int = 3600):
    while True:
        await notify_heartbeat()
        await asyncio.sleep(interval)

async def panic_close_all():
    try:
        close_all_positions()
        await notify_info("🛑 Panic Button: כל הפוזיציות נסגרו!")
    except Exception as e:
        await notify_error(f"Panic close failed: {e}")

def record_health(ok: bool):
    global _health_fails, _cap_triggered
    if ok:
        _health_fails = 0
        return
    _health_fails += 1
    if _health_fails >= _HEALTH_FAIL_MAX and not _cap_triggered:
        _cap_triggered = True
        asyncio.create_task(panic_close_all())
        logger.error("🚨 KillSwitch triggered — too many /health fails")

async def handle_order_filled(event: Dict[str, Any]):
    try:
        clid = (event.get("clientOrderId") or "").upper()
        symbol = (event.get("symbol") or "").upper()
        if not symbol or not clid:
            return
        is_tp1 = any(tag.upper() in clid for tag in _TP1_TAGS)
        if not is_tp1:
            return

        if _set_be_native:
            try:
                _ = _set_be_native(symbol, offset_bps=TP_BE_OFFSET_BPS)
                await notify_sl_tp_update(symbol, "AUTO", "breakeven", f"entry±{TP_BE_OFFSET_BPS}bps")
                with suppress(Exception):
                    ensure_protective_stop(symbol, prefer_mode="native")
                return
            except Exception as e:
                logger.error("[tm.order_filled] native BE failed: %s", e)

        open_positions = get_open_positions() or []
        for pos in open_positions:
            try:
                if (pos.get("symbol") or "").upper() != symbol:
                    continue
                amt = float(pos.get("positionAmt", "0"))
                if abs(amt) < 1e-12:
                    continue
                side = "LONG" if amt > 0 else "SHORT"
                entry = float(pos.get("entryPrice", "0"))
                if entry <= 0:
                    continue
                modify_stop_loss(symbol, entry, position_side=side)
                await notify_sl_tp_update(symbol, side, "breakeven", entry)
                with suppress(Exception):
                    ensure_protective_stop(symbol, prefer_mode="native")
                break
            except Exception:
                continue
    except Exception as e:
        logger.error("[tm.order_filled] error: %s", e)

async def _be_guard_tick():
    global _last_be_guard
    now = time.time()
    if now - _last_be_guard < _BE_GUARD_EVERY_SEC:
        return
    _last_be_guard = now

    if not futures_mark_price or not get_open_orders:
        return

    tp1_pct = _tp1_pct_default() / 100.0
    positions = get_open_positions() or []
    for pos in positions:
        try:
            symbol = (pos.get("symbol") or "").upper()
            if not symbol:
                continue
            amt = float(pos.get("positionAmt", "0"))
            if abs(amt) < 1e-12:
                continue
            entry = float(pos.get("entryPrice", "0"))
            if entry <= 0:
                continue
            side = "LONG" if amt > 0 else "SHORT"

            mark = futures_mark_price(symbol) or 0.0
            if mark <= 0:
                continue

            reached = (mark >= entry * (1.0 + tp1_pct)) if side == "LONG" else (mark <= entry * (1.0 - tp1_pct))
            if not reached:
                continue

            orders = get_open_orders(symbol) or []
            be_like = False
            for o in orders:
                otype = (o.get("type") or "").upper()
                if "STOP" not in otype:
                    continue
                stop_px = float(o.get("stopPrice") or o.get("price") or 0)
                if side == "LONG" and stop_px >= entry:
                    be_like = True
                if side == "SHORT" and stop_px <= entry:
                    be_like = True
            if be_like:
                continue

            if symbol in _be_set_once:
                continue

            if _set_be_native:
                _ = _set_be_native(symbol, offset_bps=TP_BE_OFFSET_BPS)
                await notify_sl_tp_update(symbol, side, "breakeven", f"entry±{TP_BE_OFFSET_BPS}bps")
            else:
                modify_stop_loss(symbol, entry, position_side=side)
                await notify_sl_tp_update(symbol, side, "breakeven", entry)

            with suppress(Exception):
                ensure_protective_stop(symbol, prefer_mode="native")

            _be_set_once.add(symbol)
            logger.info("[tm.be_guard] %s BE set", symbol)
        except Exception as e:
            logger.error("[tm.be_guard] error: %s", e)












