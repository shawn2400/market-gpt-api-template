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

logger = logging.getLogger("algogpt.trade_manager")

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

# Prefix policy for cancels
ORDER_ID_PREFIX = os.getenv("ORDER_ID_PREFIX", "").strip()
CANCEL_ONLY_PREFIXED_ORDERS = os.getenv("CANCEL_ONLY_PREFIXED_ORDERS", "0").lower() in ("1", "true", "yes", "on")
CANCEL_PREFIX_OVERRIDE = os.getenv("CANCEL_PREFIX_OVERRIDE", "").strip()

# Limit offsets (align עם trade_executor)
SL_LIMIT_OFFSET_BPS = float(os.getenv("SL_LIMIT_OFFSET_BPS", "8"))
TP_LIMIT_OFFSET_BPS = float(os.getenv("TP_LIMIT_OFFSET_BPS", "8"))

# Freeze Trailing (adaptive)
_TRAIL_FREEZE_ENABLE = os.getenv("TRAIL_FREEZE_ENABLE", "0").lower() in ("1", "true", "yes", "on")
_TRAIL_FREEZE_MIN_SEC = int(os.getenv("TRAIL_FREEZE_MIN_SEC", "60"))
_TRAIL_FREEZE_MAX_SEC = int(os.getenv("TRAIL_FREEZE_MAX_SEC", "180"))
_TRAIL_FREEZE_SPIKE_ATR_MULT = float(os.getenv("TRAIL_FREEZE_SPIKE_ATR_MULT", "1.8"))
_TRAIL_FREEZE_ADX_WEAK = float(os.getenv("TRAIL_FREEZE_ADX_WEAK", "20"))
_last_trail_freeze_until: Dict[str, float] = {}

# “Breathing” SL – שמירת רווח בזמן תיקון
SL_BREATH_ALLOW = os.getenv("SL_BREATH_ALLOW", "1").lower() in ("1", "true", "yes", "on")
SL_BREATH_ATR_MULT = float(os.getenv("SL_BREATH_ATR_MULT", "1.0"))  # כמה ATR לשחרר בזמן תיקון
LOCK_PROFIT_KEEP_RATIO = float(os.getenv("LOCK_PROFIT_KEEP_RATIO", "0.8"))  # שמירת 80% מהרווח
BREATH_COND_MIN_PROFIT_PCT = float(os.getenv("BREATH_COND_MIN_PROFIT_PCT", "0.8"))  # נשימה רק מעל רווח מינימלי

# Daily Cap / KillSwitch
DAILY_LOSS_CAP = float(os.getenv("DAILY_HARD_LOSS_USD", "-150"))
_daily_pnl = 0.0
_trades_today: List[dict] = []
_cap_triggered = False

# Kill-Switch tracking
_health_fails = 0
_HEALTH_FAIL_MAX = int(os.getenv("KILLSWITCH_THRESHOLD", "3"))

REVIEW_PATH = Path("static/cache/trade_reviews.json")

# Optional Ops Guard (non-blocking)
try:
    from utils.ops_guard import ops_tick
except Exception:
    async def ops_tick(**kwargs):  # type: ignore
        return None

# Price age (optional)
try:
    get_price_age = ws_fallback.get_price_age  # type: ignore
except Exception:
    def get_price_age(symbol: str):  # type: ignore
        return None

# Config gates (presence only; לא נחסם אם חסר)
try:
    from utils.config import ALLOW_MANAGE_OPEN_TRADES, AUTO_RUN  # noqa: F401
except Exception:
    ALLOW_MANAGE_OPEN_TRADES, AUTO_RUN = True, True  # safe defaults

# Telegram notifier
from utils.telegram_notifier import (
    notify_sl_tp_update,
    notify_info,
    notify_error,
    notify_heartbeat,
    notify_daily_summary,
)

# ──────────────────────────────────────────────────────────────────────────────
# Local quantizers (tick/step from exchangeInfo)
# ──────────────────────────────────────────────────────────────────────────────
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


# ──────────────────────────────────────────────────────────────────────────────
# SL/TP helpers (MARK_PRICE triggers)
# ──────────────────────────────────────────────────────────────────────────────
def _cancel_closing_orders(symbol: str, types: Tuple[str, ...]) -> int:
    """בטל הזמנות TP/SL פעילות לפי סוגים, בהתאם למדיניות פריפיקס."""
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
    """מאחזר את מחיר ה-STOP הפעיל הקרוב ביותר (MARKET/STOP) לפי צד הפוזיציה."""
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
    # LONG → הגבוה ביותר; SHORT → הנמוך ביותר
    return max(stops) if side.upper() == "LONG" else min(stops)


def modify_stop_loss(
    symbol: str,
    new_price: float,
    *,
    position_side: str = "LONG",
    qty_hint: Optional[float] = None,
) -> Dict[str, Any]:
    """ביטול SL ישן → יצירת STOP_MARKET חדש (MARK_PRICE)."""
    sym = symbol.upper()
    close_side = "SELL" if position_side.upper() == "LONG" else "BUY"
    _cancel_closing_orders(sym, ("STOP", "STOP_MARKET"))
    stop_str, _ = _q_price(sym, float(new_price))
    qty = qty_hint
    if not qty or qty <= 0:
        try:
            for p in get_open_positions(sym):
                amt = float(p.get("positionAmt") or 0.0)
                if abs(amt) > 0:
                    qty = abs(amt)
                    break
        except Exception:
            pass
    if not qty or qty <= 0:
        return {"ok": False, "error": "qty_missing_for_modify_sl"}
    qty_str, _ = _q_qty(sym, float(qty))
    try:
        resp = futures_create_order(
            symbol=sym,
            side=close_side,
            type="STOP_MARKET",
            reduceOnly=True,
            stopPrice=stop_str,
            quantity=qty_str,
            workingType="MARK_PRICE",
            timeInForce="GTC",
        )
        return {"ok": True, "response": resp}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def modify_take_profit(
    symbol: str,
    new_price: float,
    *,
    position_side: str = "LONG",
    qty_hint: Optional[float] = None,
) -> Dict[str, Any]:
    """ביטול TP ישן → TAKE_PROFIT (limit) עם OFFSET קטן (או MARKET לפי צורך)."""
    sym = symbol.upper()
    close_side = "SELL" if position_side.upper() == "LONG" else "BUY"
    _cancel_closing_orders(sym, ("TAKE_PROFIT", "TAKE_PROFIT_MARKET"))
    stop_str, stop_px = _q_price(sym, float(new_price))
    limit_px = _offset_bps(stop_px, TP_LIMIT_OFFSET_BPS, +1 if close_side == "SELL" else -1)
    price_str, _ = _q_price(sym, float(limit_px))
    qty = qty_hint
    if not qty or qty <= 0:
        try:
            for p in get_open_positions(sym):
                amt = float(p.get("positionAmt") or 0.0)
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
            reduceOnly=True,
            stopPrice=stop_str,
            price=price_str,
            quantity=qty_str,
            timeInForce="GTC",
            workingType="MARK_PRICE",
        )
        return {"ok": True, "response": resp}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# Breakeven native (optional)
try:
    from utils.binance_client import set_breakeven_stop as _set_be_native  # type: ignore
except Exception:
    _set_be_native = None  # type: ignore

# ──────────────────────────────────────────────────────────────────────────────
# State
# ──────────────────────────────────────────────────────────────────────────────
_last_update: Dict[str, float] = {}
_last_be_guard = 0.0
_be_set_once: set[str] = set()
_prev_open_positions: Dict[str, Dict[str, Any]] = {}


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────
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


# ──────────────────────────────────────────────────────────────────────────────
# AI review on closures
# ──────────────────────────────────────────────────────────────────────────────
async def _detect_closures_and_review(curr_positions: List[Dict[str, Any]]) -> None:
    global _prev_open_positions
    try:
        curr_open: Dict[str, Dict[str, Any]] = {}
        for p in curr_positions or []:
            try:
                sym = (p.get("symbol") or "").upper()
                amt = float(p.get("positionAmt") or 0)
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
                ctx = {
                    "entry": entry,
                    "exit": exit_px,
                    "pnl_usd": None,
                    "rr": None,
                    "indicators": {},
                    "reasons": ["auto_detected_closure"],
                }
                try:
                    await review_trade_async(s, side, ctx, to_telegram=True)
                except Exception as e:
                    logger.warning("[ai_review] failed for %s: %s", s, e)

        _prev_open_positions = curr_open
    except Exception as e:
        logger.debug("[ai_review] closure detect error: %s", e)


# ──────────────────────────────────────────────────────────────────────────────
# Trailing freeze (adaptive)
# ──────────────────────────────────────────────────────────────────────────────
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
        logger.info(
            {
                "event": "trail_freeze",
                "symbol": symbol,
                "dur_sec": dur,
                "spike_mult": round(spike_mult, 2),
                "adx": round(adx_now, 1),
                "macd_delta": round(macd_diff_now, 2),
            }
        )
        return True
    return False


# ──────────────────────────────────────────────────────────────────────────────
# Core loop
# ──────────────────────────────────────────────────────────────────────────────
async def manage_open_trades():
    global _daily_pnl, _cap_triggered
    if not ALLOW_MANAGE_OPEN_TRADES or _cap_triggered:
        return

    try:
        positions = get_open_positions() or []
        now = time.time()
        for pos in positions:
            try:
                sym = (pos.get("symbol") or "").upper()
                qty = float(pos.get("positionAmt") or 0)
                entry = float(pos.get("entryPrice") or 0)
                if not sym or entry <= 0 or abs(qty) <= 0:
                    continue
                side = "LONG" if qty > 0 else "SHORT"
                price = _price_now(sym)
                if price <= 0:
                    continue

                # Per-symbol cooldown
                if now - _last_update.get(sym, 0) < _COOLDOWN:
                    continue

                df = get_klines_df(sym, interval="5m", limit=50)
                if df is None or getattr(df, "empty", False):
                    continue

                atr_series = atr(df)
                adx_series = adx(df)
                current_atr = float(atr_series.iloc[-1]) if hasattr(atr_series, "iloc") else float(atr_series[-1])
                current_adx = float(adx_series.iloc[-1]) if hasattr(adx_series, "iloc") else float(adx_series[-1])
                macd_line, macd_signal, _ = macd(df["close"])
                macd_now = float(macd_line.iloc[-1] - macd_signal.iloc[-1])

                if not (_is_finite_number(current_atr) and current_atr > 0):
                    continue
                if not _is_finite_number(current_adx):
                    continue
                if not _is_finite_number(macd_now):
                    continue

                profit_pct = abs((price - entry) / entry) * 100.0

                # Soft Breakeven
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

                # Trailing with freeze
                if _maybe_freeze_trailing(sym, df, current_atr, current_adx, macd_now):
                    _last_update[sym] = now
                    continue

                # Baseline SL (ATR + swing)
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
                    continue

                # Breathing: שחרור עדין בטווח תיקון, תוך שמירת 80% מהרווח
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

                # אל תזיז SL “רע” מתחת/מעל BE אם כבר הוזז ל-BE
                cur_stop = _current_stop(sym, side) or entry
                if side == "LONG":
                    if (cur_stop >= entry) and (target_sl < entry):
                        target_sl = max(entry, target_sl)
                else:
                    if (cur_stop <= entry) and (target_sl > entry):
                        target_sl = min(entry, target_sl)

                # עדכון בפועל רק אם שינוי מהותי (מונע הצפה)
                try:
                    if _is_finite_number(target_sl) and _is_finite_number(cur_stop):
                        thresh = 0.25 * current_atr
                        need_update = (abs(target_sl - float(cur_stop)) >= thresh)
                        if need_update:
                            modify_stop_loss(sym, target_sl, position_side=side)
                            await notify_sl_tp_update(sym, side, "trailing", target_sl)
                except Exception as e:
                    logger.error("[manage] trailing update failed for %s: %s", sym, e)

                # Dynamic TP (lock-in תחת מומנטום/ADX)
                try:
                    if current_adx > 25 and macd_now > 0:
                        new_tp = (price + 4.5 * current_atr) if side == "LONG" else (price - 4.5 * current_atr)
                        if _is_finite_number(new_tp):
                            modify_take_profit(sym, new_tp, position_side=side)
                            await notify_sl_tp_update(sym, side, "tp", new_tp)
                except Exception as e:
                    logger.error("[manage] TP update failed for %s: %s", sym, e)

                _last_update[sym] = now

            except Exception as ie:
                logger.error("[manage] per-position error %s: %s", pos.get("symbol"), ie)

        # Sparse BE guard
        if _BE_GUARD_ENABLE:
            await _be_guard_tick()

        # Closure detection + AI review
        await _detect_closures_and_review(positions)

        # Ops tick: price TTL if available
        try:
            ttl = get_price_age("BTCUSDT")
            await ops_tick(price_ttl_sec=float(ttl) if ttl is not None else None)
        except Exception:
            pass

        # Daily Cap
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


# ──────────────────────────────────────────────────────────────────────────────
# On order filled (TP1 tag → BE)
# ──────────────────────────────────────────────────────────────────────────────
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
                break
            except Exception:
                continue
    except Exception as e:
        logger.error("[tm.order_filled] error: %s", e)


# ──────────────────────────────────────────────────────────────────────────────
# Sparse BE Guard (time-based)
# ──────────────────────────────────────────────────────────────────────────────
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

            _be_set_once.add(symbol)
            logger.info("[tm.be_guard] %s BE set", symbol)
        except Exception as e:
            logger.error("[tm.be_guard] error: %s", e)

















