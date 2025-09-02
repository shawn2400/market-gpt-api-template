# utils/open_trade_manager.py
from __future__ import annotations
import os, time, asyncio, logging
from typing import Dict, Any, List, Optional, Tuple

import requests
import pandas as pd

from utils import config as cfg
from utils.indicators import prepare_indicators_for_backtest
from utils.ws_fallback import get_price, is_price_fresh
from utils.precision_utils import apply_price_tick_side
from utils.binance_client import (
    futures_mark_price,
    place_stop_market,
    place_take_profit_market,
)

logger = logging.getLogger("algogpt.open_trade_manager")

# ---------------------------
# ENV tuning (ללא שינוי ב-config.py)
# ---------------------------
def _as_bool(s: Optional[str], default=False) -> bool:
    return str(s).strip().lower() in {"1","true","yes","on"} if s is not None else default
def _as_float(s: Optional[str], default: float) -> float:
    try: return float(str(s).strip())
    except: return default
def _as_int(s: Optional[str], default: int) -> int:
    try: return int(str(s).strip())
    except: return default

# Chop / Momentum
CHOP_DETECT_ENABLE   = _as_bool(os.getenv("CHOP_DETECT_ENABLE","true"), True)
CHOP_ADX_MAX         = _as_float(os.getenv("CHOP_ADX_MAX","18"), 18.0)
CHOP_MACD_HIST_ABS_MAX = _as_float(os.getenv("CHOP_MACD_HIST_ABS_MAX","0.05"), 0.05)
CHOP_BB_WIDTH_PCT_MAX  = _as_float(os.getenv("CHOP_BB_WIDTH_PCT_MAX","0.9"), 0.9)
CHOP_MIN_BARS        = _as_int(os.getenv("CHOP_MIN_BARS","6"), 6)
CHOP_TIME_LIMIT_MIN  = _as_int(os.getenv("CHOP_TIME_LIMIT_MIN","45"), 45)
CHOP_ACTION          = (os.getenv("CHOP_ACTION","to_breakeven") or "to_breakeven").strip()  # to_breakeven|partial_exit|full_exit
CHOP_PARTIAL_PCT     = _as_float(os.getenv("CHOP_PARTIAL_PCT","0.33"), 0.33)

# Breakeven & Trailing
BE_ARM_PCT           = _as_float(os.getenv("BE_ARM_PCT","1.6"), 1.6)  # % מהכניסה
TRAIL_ATR_MULT       = _as_float(os.getenv("TRAIL_ATR_MULT", str(cfg.STOP_LOSS_ATR_MULTIPLIER)), cfg.STOP_LOSS_ATR_MULTIPLIER)

# Momentum lock & TP shift
MOMENTUM_LOCK_MIN_BARS = _as_int(os.getenv("MOMENTUM_LOCK_MIN_BARS","3"), 3)
MOMENTUM_TP_SHIFT_ATR  = _as_float(os.getenv("MOMENTUM_TP_SHIFT","0.5"), 0.5) # הסטת TP ב*ATR

# Cooldown / noise control
MANAGER_COOLDOWN_SEC = _as_int(os.getenv("MANAGER_COOLDOWN_SEC","45"), 45)
MIN_TP_SL_DIFF_TICKS = _as_int(os.getenv("MIN_TP_SL_DIFF_TICKS","2"), 2)  # לא משנים אם ההבדל קטן מ-2 טיקים
MIN_TP_SL_DIFF_PCT   = _as_float(os.getenv("MIN_TP_SL_DIFF_PCT","0.15"), 0.15)  # וגם לא משנים אם <0.15%

# Klines
FUTURES_BASE = cfg.BINANCE_FUTURES_HTTP_BASE
KL_INTERVAL  = os.getenv("MANAGER_SCAN_INTERVAL", cfg.DEFAULT_INTERVAL)  # 15m
KL_LIMIT     = _as_int(os.getenv("MANAGER_SCAN_LIMIT","200"), 200)

# Executor state
_MANAGER_RUNNING: bool = False
_manager_task: Optional[asyncio.Task] = None
_last_touch: Dict[str, float] = {}         # per-symbol cooldown
_lock_momentum_until: Dict[str, int] = {}  # per-symbol bar countdown

# Optional API (cancel/get orders) — לא בטוח קיים אצלך → Fallback בטוח
def _get_open_orders_or_none(symbol: str) -> Optional[List[Dict[str, Any]]]:
    try:
        from utils.binance_client import get_open_orders
        return get_open_orders(symbol)
    except Exception:
        return None

def _cancel_order_safe(symbol: str, order_id: Optional[int]) -> bool:
    if not order_id:
        return False
    try:
        from utils.binance_client import cancel_order
        cancel_order(symbol, order_id)
        return True
    except Exception:
        try:
            from utils.binance_client import cancel_open_orders
            cancel_open_orders(symbol)
            return True
        except Exception as e:
            logger.warning({"event":"cancel_order_unavailable", "symbol":symbol, "err": str(e)})
            return False

# ---------------------------
# Helpers
# ---------------------------
def _fresh_price(symbol: str) -> Optional[float]:
    if is_price_fresh(symbol, max_age_sec=int(os.getenv("PRICE_MAX_AGE_SEC","10"))):
        return get_price(symbol)
    try:
        return float(futures_mark_price(symbol) or 0.0)
    except Exception:
        return None

def _align_price(symbol: str, price: float, side_for_tick: str) -> float:
    px, _ = apply_price_tick_side(price, symbol, side_for_tick)
    return float(px)

def _pct(from_px: float, to_px: float) -> float:
    if not from_px: return 0.0
    return (to_px/from_px - 1.0) * 100.0

def _enough_move(curr: float, target: float, tick: float, pct_gate: float) -> bool:
    if curr <= 0 or target <= 0: return True
    diff = abs(target - curr)
    return (diff >= (tick * MIN_TP_SL_DIFF_TICKS)) and (abs((target/curr - 1.0)*100.0) >= pct_gate)

def _now() -> float:
    return time.time()

async def _klines_df(symbol: str, interval: str, limit: int) -> pd.DataFrame:
    url = f"{FUTURES_BASE}/fapi/v1/klines"
    r = requests.get(url, params={"symbol": symbol, "interval": interval, "limit": limit}, timeout=10)
    r.raise_for_status()
    arr = r.json()
    cols = ["open_time","open","high","low","close","volume","close_time","qv","nTrades","taker_base","taker_quote","x"]
    df = pd.DataFrame(arr, columns=cols[:len(arr[0])])
    for c in ("open","high","low","close","volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df

def _bb_width_pct(row: Dict[str, Any]) -> float:
    mid = float(row.get("bb_mid") or 0.0)
    up  = float(row.get("bb_upper") or 0.0)
    lo  = float(row.get("bb_lower") or 0.0)
    if mid <= 0 or up <= 0 or lo <= 0: return 0.0
    return (up - lo) / mid * 100.0

def _momentum_ok(side: str, row: Dict[str, Any]) -> bool:
    adx = float(row.get("adx") or 0.0)
    macd_hist = float(row.get("macd_hist") or 0.0)
    if side.upper() in ("BUY","LONG"):
        return (adx >= 25.0) and (macd_hist > 0.0)
    else:
        return (adx >= 25.0) and (macd_hist < 0.0)

def _chop_now(window: List[Dict[str, Any]]) -> bool:
    if not CHOP_DETECT_ENABLE: return False
    if len(window) < CHOP_MIN_BARS: return False
    last = window[-CHOP_MIN_BARS:]
    adx_ok = all(float(r.get("adx") or 0.0) < CHOP_ADX_MAX for r in last)
    macd_ok = all(abs(float(r.get("macd_hist") or 0.0)) <= CHOP_MACD_HIST_ABS_MAX for r in last)
    bb_ok = all(_bb_width_pct(r) <= CHOP_BB_WIDTH_PCT_MAX for r in last)
    return bool(adx_ok and macd_ok and bb_ok)

def _side_to_close(side: str) -> str:
    return "SELL" if side.upper() in ("BUY","LONG") else "BUY"

# Position fetch — primary: Binance API (אם קיים), fallback: trade_manager Redis
def _fetch_positions() -> List[Dict[str, Any]]:
    # נסה utils.binance_client.futures_position_risk()
    try:
        from utils.binance_client import futures_position_risk
        pos = futures_position_risk() or []
        # Normalize
        out=[]
        for p in pos:
            try:
                amt = float(p.get("positionAmt") or 0.0)
                if abs(amt) <= 0: continue
                sym = str(p.get("symbol") or "").upper()
                entry = float(p.get("entryPrice") or 0.0)
                lev = float(p.get("leverage") or 1.0)
                side = "LONG" if amt > 0 else "SHORT"
                u = {
                    "symbol": sym,
                    "side": side,
                    "qty": abs(amt),
                    "entry": entry,
                    "leverage": lev,
                    "unrealizedPnl": float(p.get("unRealizedProfit") or 0.0),
                    "updateTime": int(p.get("updateTime") or 0),
                    "notional": abs(float(p.get("notional") or amt*entry)),
                }
                out.append(u)
            except Exception:
                continue
        return out
    except Exception:
        pass

    # Fallback: Redis-based open trades
    try:
        from utils.trade_manager import get_open_trades
        raw = get_open_trades()
        out=[]
        for t in (raw or []):
            out.append({
                "symbol": t.get("symbol","").upper(),
                "side": t.get("side","").upper(),
                "qty": float(t.get("qty") or 0.0),
                "entry": float(t.get("entry_price") or 0.0),
                "leverage": float(t.get("leverage") or cfg.MIN_LEVERAGE),
                "unrealizedPnl": 0.0,
                "updateTime": 0,
                "notional": float(t.get("qty") or 0.0) * float(t.get("entry_price") or 0.0),
            })
        return out
    except Exception as e:
        logger.warning({"event":"fetch_positions_fallback_failed", "err": str(e)})
        return []

# ---------------------------
# Core management (single symbol)
# ---------------------------
async def _manage_symbol(sym: str, side: str, qty: float, entry: float) -> Dict[str, Any]:
    """מחשב ATR/ADX/MACD, מזהה דשדוש/מומנטום, מזיז SL/TP בבטחה (Reduce-Only)."""
    side_u = side.upper()
    close_side = _side_to_close(side_u)

    # Cooldown per symbol
    last = _last_touch.get(sym, 0.0)
    if (_now() - last) < MANAGER_COOLDOWN_SEC:
        return {"symbol": sym, "skipped": "cooldown"}

    # Price
    px = _fresh_price(sym)
    if not px or px <= 0.0:
        return {"symbol": sym, "skipped": "no_price"}

    # Indicators (klines)
    try:
        df = await _klines_df(sym, KL_INTERVAL, KL_LIMIT)
        ind = prepare_indicators_for_backtest(df)
        if ind.empty: return {"symbol": sym, "skipped": "no_indicators"}
        # נשמור סגמנט אחרון לעבודה
        tail: List[Dict[str, Any]] = [ind.iloc[i].to_dict() for i in range(max(0, len(ind)-50), len(ind))]
        row = tail[-1]
        atr = float(row.get("atr") or 0.0)
        adx = float(row.get("adx") or 0.0)
        macd_hist = float(row.get("macd_hist") or 0.0)
    except Exception as e:
        return {"symbol": sym, "error": f"indicators_failed: {e}"}

    if atr <= 0.0:
        return {"symbol": sym, "skipped": "atr_zero"}

    # Compute BE/Trail/TP candidates
    be_arm_px = entry * (1.0 + (BE_ARM_PCT/100.0)) if side_u in ("BUY","LONG") else entry * (1.0 - (BE_ARM_PCT/100.0))
    # ATR trailing around current price
    if side_u in ("BUY","LONG"):
        trail_sl_raw = px - (TRAIL_ATR_MULT * atr)
        be_px = max(entry, trail_sl_raw)  # לא נרד מתחת לכניסה אם BE כבר אפשרי
        trail_sl = _align_price(sym, be_px, "SELL")
        # TP shift אם מומנטום חזק
        tp_shift = MOMENTUM_TP_SHIFT_ATR * atr if _momentum_ok(side_u, row) else 0.0
    else:
        trail_sl_raw = px + (TRAIL_ATR_MULT * atr)
        be_px = min(entry, trail_sl_raw)
        trail_sl = _align_price(sym, be_px, "BUY")
        tp_shift = -MOMENTUM_TP_SHIFT_ATR * atr if _momentum_ok(side_u, row) else 0.0

    # Chop detection window
    is_chop = _chop_now(tail)
    # Profit % now
    pnl_pct = _pct(entry, px) if side_u in ("BUY","LONG") else _pct(px, entry)

    # Decide SL & TP
    desired_sl = trail_sl
    # TP: אם יש shift חיובי, נרחיק TP; אחרת נשאיר/לא נגע אם אין שינוי
    # If אין לנו TP נוכחי, נשים מטרה שמרנית: entry ± 2*ATR
    base_tp = (entry + 2*atr) if side_u in ("BUY","LONG") else (entry - 2*atr)
    desired_tp = base_tp + tp_shift
    desired_tp = _align_price(sym, desired_tp, close_side)

    # Chop strategy
    chop_action_taken = None
    minutes_alive = 0
    try:
        # אם יש updateTime בפוזיציה, נחשב זמן חיים מקורב
        minutes_alive = max(0, int((_now() - (row.get("close_time", _now())/1000 if isinstance(row.get("close_time"), (int,float)) else _now()))/60))
    except Exception:
        pass

    if is_chop:
        if CHOP_ACTION == "to_breakeven" and pnl_pct >= 0.0:
            desired_sl = _align_price(sym, entry, close_side)
            chop_action_taken = "SL->BE"
        elif CHOP_ACTION == "partial_exit" and pnl_pct >= 0.0 and minutes_alive >= CHOP_TIME_LIMIT_MIN:
            # נבצע partial exit ע"י הזזת TP קרוב (למשל entry ± 0.5*ATR) על חלק מהכמות
            desired_tp = _align_price(sym, (entry + (0.5*atr if side_u in ("BUY","LONG") else -0.5*atr)), close_side)
            # בפועל, נשתמש בכמות קטנה יותר אם יש פונקציית הזמנה גמישה
            chop_action_taken = f"partial_exit~{int(CHOP_PARTIAL_PCT*100)}%"
        elif CHOP_ACTION == "full_exit" and minutes_alive >= CHOP_TIME_LIMIT_MIN:
            # TP קרוב למידית יציאה
            desired_tp = _align_price(sym, (entry + (0.15*atr if side_u in ("BUY","LONG") else -0.15*atr)), close_side)
            chop_action_taken = "force_exit"

    # Breakeven arm אם המחיר עבר BE_ARM_PCT
    if (side_u in ("BUY","LONG") and px >= be_arm_px) or (side_u in ("SELL","SHORT") and px <= be_arm_px):
        desired_sl = max(desired_sl, entry) if side_u in ("BUY","LONG") else min(desired_sl, entry)

    # Momentum lock (לא סוגרים מוקדם)
    lock_key = f"{sym}:{side_u}"
    if _momentum_ok(side_u, row):
        # ננעל לכמות נרות
        _lock_momentum_until[lock_key] = max(_lock_momentum_until.get(lock_key, 0), MOMENTUM_LOCK_MIN_BARS)
    else:
        # אם יש נעילה — נוריד ב-1 כל קריאה (כל נר ≈ Interval; כאן אנחנו בודקים כל X שניות → עדיין נותן “חמצן”)
        if _lock_momentum_until.get(lock_key, 0) > 0:
            _lock_momentum_until[lock_key] -= 1

    # אם נעול מומנטום — אל תקרב SL מעבר ל-trailing המחושב (לא נסגור מוקדם יותר)
    # (כבר מטופל לוגית ע"י בחירה מחמירה של desired_sl, אבל נשמור guard)
    # ---------- Sync to Binance ----------
    # נביא הזמנות פתוחות (אם יש API) כדי לעדכן רק אם צריך
    open_orders = _get_open_orders_or_none(sym)
    current_sl = None
    current_tp = None
    sl_order_id = None
    tp_order_id = None

    try:
        if open_orders:
            for o in open_orders:
                ty = str(o.get("type","")).upper()
                ro = bool(o.get("reduceOnly") or (str(o.get("reduceOnly","")).lower()=="true"))
                sp = float(o.get("stopPrice") or o.get("price") or 0.0)
                oid = o.get("orderId")
                if not ro:  # אנחנו לא נוגעים בפקודות שאינן Reduce-Only
                    continue
                if ty in ("STOP_MARKET","STOP","STOP_LOSS","STOP_LOSS_LIMIT"):
                    current_sl, sl_order_id = sp, oid
                elif ty in ("TAKE_PROFIT_MARKET","TAKE_PROFIT","TAKE_PROFIT_LIMIT"):
                    current_tp, tp_order_id = sp, oid
    except Exception:
        pass

    # Decide if to update
    # Tick: נחלץ מטיק דרך apply_price_tick_side (הפונקציה מחזירה גם סטייה, אבל מספיק לנו לקוונט את היעד)
    # בשביל gate נוסף — נשתמש בסף אחוזי קטן כדי למנוע churn.
    need_sl = (current_sl is None) or _enough_move(float(current_sl or 0.0), desired_sl, tick=abs(desired_sl - _align_price(sym, desired_sl + 1e-9, close_side)), pct_gate=MIN_TP_SL_DIFF_PCT)
    need_tp = (current_tp is None) or _enough_move(float(current_tp or 0.0), desired_tp, tick=abs(desired_tp - _align_price(sym, desired_tp + 1e-9, close_side)), pct_gate=MIN_TP_SL_DIFF_PCT)

    changed = False
    errors: List[str] = []

    if not _as_bool(os.getenv("ALLOW_MANAGE_OPEN_TRADES","true"), True):
        return {"symbol": sym, "skipped": "ALLOW_MANAGE_OPEN_TRADES=false"}

    # עדכון SL
    if need_sl:
        try:
            # ננסה לבטל SL קודם (אם יש API), כדי למנוע כפילויות
            if sl_order_id:
                _cancel_order_safe(sym, sl_order_id)
            place_stop_market(sym, close_side, float(desired_sl), float(qty), reduce_only=True)
            changed = True
        except Exception as e:
            errors.append(f"sl_update_failed:{e}")

    # עדכון TP
    if need_tp:
        try:
            if tp_order_id:
                _cancel_order_safe(sym, tp_order_id)
            place_take_profit_market(sym, close_side, float(desired_tp), float(qty), reduce_only=True)
            changed = True
        except Exception as e:
            errors.append(f"tp_update_failed:{e}")

    _last_touch[sym] = _now()
    return {
        "symbol": sym,
        "side": side_u,
        "entry": entry,
        "price": px,
        "pnl_pct": round(pnl_pct, 4),
        "adx": round(adx, 3),
        "macd_hist": round(macd_hist, 5),
        "atr": round(atr, 6),
        "is_chop": bool(is_chop),
        "desired_sl": desired_sl,
        "desired_tp": desired_tp,
        "changed": changed,
        "chop_action": chop_action_taken,
        "errors": errors,
    }

# ---------------------------
# Public API
# ---------------------------
async def manage_open_trades() -> Dict[str, Any]:
    """
    עובר על כל הפוזיציות הפתוחות ומבצע ניהול חי:
    - SL → BE / Trailing ATR
    - TP → Shift עם מומנטום
    - Chop → BE/Partial/Exit לפי פרמטרים
    שומר על קירור, מפחית עומס, משנה רק כשיש סטייה משמעותית.
    """
    positions = _fetch_positions()
    if not positions:
        return {"ok": True, "managed": 0, "details": [], "note": "no_positions"}

    details=[]
    for p in positions:
        try:
            sym = p["symbol"].upper()
            side = p["side"].upper()
            qty  = float(p["qty"])
            entry= float(p["entry"])
            if qty <= 0 or entry <= 0:
                details.append({"symbol": sym, "skip": "bad_qty_or_entry"})
                continue
            res = await _manage_symbol(sym, side, qty, entry)
            details.append(res)
        except Exception as e:
            details.append({"symbol": p.get("symbol","?"), "error": str(e)})

    changed = sum(1 for d in details if d.get("changed")) if isinstance(details, list) else 0
    return {"ok": True, "managed": len(details), "changed": changed, "details": details}

# Loop controls (לשימוש ב-main / ראוטרים)
async def _manager_loop(interval_sec: int):
    global _MANAGER_RUNNING
    _MANAGER_RUNNING = True
    try:
        while _MANAGER_RUNNING:
            try:
                res = await manage_open_trades()
                logger.info({"event": "manage_tick", "changed": res.get("changed", 0)})
            except Exception as e:
                logger.error({"event": "manage_iteration_error", "error": str(e)})
            await asyncio.sleep(max(10, int(interval_sec)))
    finally:
        _MANAGER_RUNNING = False

def start_manager(interval_sec: int = 60) -> None:
    global _manager_task, _MANAGER_RUNNING
    if _MANAGER_RUNNING:
        logger.info({"event": "manager_already_running"})
        return
    loop = asyncio.get_event_loop()
    _manager_task = loop.create_task(_manager_loop(interval_sec))
    logger.info({"event": "manager_started", "interval": interval_sec})

def stop_manager() -> None:
    global _manager_task, _MANAGER_RUNNING
    _MANAGER_RUNNING = False
    try:
        if _manager_task and not _manager_task.done():
            _manager_task.cancel()
    except Exception:
        pass
    _manager_task = None
    logger.info({"event": "manager_stopped"})


