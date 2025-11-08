# utils/position_manager.py
# -*- coding: utf-8 -*-
from __future__ import annotations
"""
Position Manager (PLUS): BE-stair פרוגרסיבי + Profit-Lock Bands + TP Merge/Rearm + ATR-Trail
---------------------------------------------------------------------------------------------
מיועד לקריאה מתוך routes/manager.py::manage_once_lite()

ENV רלוונטי:
  BE_BASE_BPS=5
  BE_ADX_FACTOR=0.2               # שמור לעתיד (כרגע לא משפיע ישיר)
  TRAIL_MIN_PCT=0.08
  TRAIL_MAX_PCT=5.0
  BINANCE_WORKING_TYPE=MARK_PRICE|CONTRACT_PRICE

  PROFIT_LOCK_STEPS="1.0,1.5,2.0" # RR ספים; RR מחושב כ(תזוזה%/BE%)
  TP_MERGE_TICK_BAND=1            # מרחק טיקים למיזוג יעדים סמוכים
  TP_REARM_TICK=1                 # מרחק טיקים להפעלה מחודשת אם היה "כמעט"

חתימה:
    async def manage_once(symbol: Optional[str] = None,
                          offset_bps: Optional[int] = None,
                          pcts: Optional[list[float]] = None,
                          splits: Optional[list[float]] = None,
                          atr_mult: Optional[float] = None) -> dict

הקובץ בטוח גם ללא Binance SDK/מפתחות — יחזיר skipped=True.
"""

import os, math, logging
from typing import Any, Dict, List, Optional, Tuple
from contextlib import suppress

logger = logging.getLogger(__name__)

# --- Metrics (אופציונלי; לא בשימוש ישיר) ---
with suppress(Exception):
    from utils.metrics_tracker import inc_scan_passed as _noop1  # noqa: F401
with suppress(Exception):
    from utils.metrics_tracker import inc_scan_blocked as _noop2  # noqa: F401

# --- COID helper (נקרא אם קיים, אחרת גרסה מקומית) ---
with suppress(Exception):
    from utils.order_ids import build_client_order_id as _build_id  # type: ignore

def _build_local_id(symbol: str, side: str, role: str = "GEN") -> str:
    import time, hashlib
    pref = (os.getenv("ORDER_ID_PREFIX") or "ALG").strip() or "ALG"
    base = f"{pref}-{symbol.upper()}-{side.upper()}-{role.upper()}-{int(time.time()*1000)}"
    if len(base) <= 36:
        return base
    h = hashlib.md5(base.encode("utf-8")).hexdigest()[:6]
    return base[:36 - (len(h) + 1)] + "_" + h

def _coid(symbol: str, side: str, role: str) -> str:
    with suppress(Exception):
        return _build_id(symbol, side, role=role)  # type: ignore
    return _build_local_id(symbol, side, role)

# --- Database helper for reading original trade parameters ---
def _get_trade_params_from_db(symbol: str) -> Optional[Dict[str, Any]]:
    """
    🔍 Query original trade parameters (SL, TP) from trades_log table.
    Returns dict with 'sl', 'tp', 'entry', 'leverage' if found, else None.
    """
    try:
        import psycopg2
        
        DATABASE_URL = os.getenv("DATABASE_URL", "")
        if not DATABASE_URL:
            return None
        
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        
        cur.execute("""
            SELECT entry, sl, tp, leverage
            FROM trades_log
            WHERE symbol = %s AND status = 'OPEN'
            ORDER BY opened_at DESC
            LIMIT 1
        """, (symbol,))
        
        row = cur.fetchone()
        cur.close()
        conn.close()
        
        if row:
            entry, sl, tp, leverage = row
            return {
                "entry": float(entry) if entry else None,
                "sl": float(sl) if sl else None,
                "tp": float(tp) if tp else None,
                "leverage": int(leverage) if leverage else None
            }
        return None
    except Exception as e:
        logger.debug(f"DB params not available for {symbol}: {e}")
        return None

# --- ENV knobs ---
BE_BASE_BPS      = int(os.getenv("BE_BASE_BPS", "5") or 5)
BE_ADX_FACTOR    = float(os.getenv("BE_ADX_FACTOR", "0.2") or 0.2)     # מוכן לשדרוג עתידי
TRAIL_MIN_PCT    = float(os.getenv("TRAIL_MIN_PCT", "0.08") or 0.08)
TRAIL_MAX_PCT    = float(os.getenv("TRAIL_MAX_PCT", "5.0") or 5.0)
BINANCE_WORKING  = os.getenv("BINANCE_WORKING_TYPE", "MARK_PRICE").upper()

PROFIT_LOCK_STEPS_ENV = (os.getenv("PROFIT_LOCK_STEPS") or "1.0,1.5,2.0").strip()
TP_MERGE_TICK_BAND    = int(os.getenv("TP_MERGE_TICK_BAND", "1") or 1)
TP_REARM_TICK         = int(os.getenv("TP_REARM_TICK", "1") or 1)

def _parse_profit_lock_steps(s: str) -> List[float]:
    out: List[float] = []
    for p in s.split(","):
        with suppress(Exception):
            v = float(p.strip())
            if v > 0:
                out.append(v)
    return sorted(out)

PROFIT_LOCK_STEPS = _parse_profit_lock_steps(PROFIT_LOCK_STEPS_ENV)

# --- math helpers (ticks/steps) ---
def _bn_round(value: float, step: float) -> float:
    if step <= 0: return value
    # Calculate precision from step size
    step_str = f"{step:.10f}".rstrip('0')
    precision = len(step_str.split('.')[-1]) if '.' in step_str else 0
    # Round to avoid floating point errors
    return round(math.floor(value / step + 1e-9) * step, precision)

def _round_tick_dir(value: float, step: float, direction: str) -> float:
    if step <= 0: return value
    q = value / step
    rounded = (math.ceil(q) if direction.lower().startswith("up") else math.floor(q)) * step
    # Format to remove floating point errors
    precision = len(str(step).rstrip('0').split('.')[-1]) if '.' in str(step) else 0
    return round(rounded, precision)

def _ticks_between(p1: float, p2: float, tick: float) -> int:
    if tick <= 0: return 0
    return int(abs(round((p1 - p2) / tick)))

def _get_filters(client, symbol: str) -> Tuple[float, float]:
    tick = 0.1
    step = 0.001
    with suppress(Exception):
        ex = client.futures_exchange_info()
        for s in ex.get("symbols", []):
            if s.get("symbol") == symbol:
                for f in s.get("filters", []):
                    if f.get("filterType") == "PRICE_FILTER":
                        tick = float(f.get("tickSize", tick))
                    elif f.get("filterType") == "LOT_SIZE":
                        step = float(f.get("stepSize", step))
                break
    return tick, step

# --- ADX/ATR (Lite) ---
def _wilder_smooth(values: List[float], period: int) -> List[float]:
    if not values or period <= 0 or len(values) < period:
        return []
    out = [sum(values[:period]) / period]
    for v in values[period:]:
        out.append((out[-1] * (period - 1) + v) / period)
    return out

def _ind_from_kl(klines: List[List[Any]], period: int = 14) -> Dict[str, float]:
    try:
        highs = [float(k[2]) for k in klines]
        lows  = [float(k[3]) for k in klines]
        closes= [float(k[4]) for k in klines]
        if len(closes) < period + 2:
            return {"price": closes[-1] if closes else 0.0, "atr": 0.0, "adx": 0.0}
        trs, plus_dm, minus_dm = [], [], []
        for i in range(1, len(closes)):
            h, l, ph, pl, pc = highs[i], lows[i], highs[i-1], lows[i-1], closes[i-1]
            trs.append(max(h - l, abs(h - pc), abs(l - pc)))
            up_move = h - ph
            down_move = pl - l
            plus_dm.append(up_move if (up_move > down_move and up_move > 0) else 0.0)
            minus_dm.append(down_move if (down_move > up_move and down_move > 0) else 0.0)
        atr_s = _wilder_smooth(trs, period)
        p_s   = _wilder_smooth(plus_dm, period)
        m_s   = _wilder_smooth(minus_dm, period)
        if not (atr_s and p_s and m_s):
            return {"price": closes[-1], "atr": 0.0, "adx": 0.0}
        plus_di = [(p/atr_s[i])*100 if atr_s[i] > 0 else 0.0 for i, p in enumerate(p_s)]
        minus_di= [(m/atr_s[i])*100 if atr_s[i] > 0 else 0.0 for i, m in enumerate(m_s)]
        dx = []
        for i in range(min(len(plus_di), len(minus_di))):
            s = plus_di[i] + minus_di[i]
            d = abs(plus_di[i] - minus_di[i])
            dx.append((d/s)*100 if s > 0 else 0.0)
        adx_s = _wilder_smooth(dx, period)
        return {
            "price": closes[-1],
            "atr": float(atr_s[-1] if atr_s else 0.0),
            "adx": float(adx_s[-1] if adx_s else 0.0)
        }
    except Exception:
        return {"price": 0.0, "atr": 0.0, "adx": 0.0}

# --- Position helpers ---
def _align_position_mode(client) -> None:
    mode_override = (os.getenv("POSITION_MODE_OVERRIDE") or "").strip().lower()
    with suppress(Exception):
        if mode_override in ("hedge", "dual", "dual_side", "dual_side_position", "dualposition"):
            client.futures_change_position_mode(dualSidePosition="true")
        elif mode_override in ("oneway", "one_way", "single", "single_side", "oneside"):
            client.futures_change_position_mode(dualSidePosition="false")

def _profit_rr(entry: float, price_now: float, be_bps: int, side: str) -> float:
    if entry <= 0 or be_bps <= 0: return 0.0
    move_pct = ((price_now - entry) / entry * 100.0) if side == "BUY" else ((entry - price_now) / entry * 100.0)
    be_pct = be_bps / 100.0  # bps -> %
    if be_pct <= 0: return 0.0
    return max(0.0, move_pct / be_pct)

def _apply_profit_lock(base_offset_bps: int, rr: float, steps: List[float]) -> int:
    """
    מגדיל את מרחק ה-BE (offset_bps) לפי מדרגות RR שחצינו.
    לדוגמה: base=5, RR>=1.5 -> 5*1.5 = 7 bps; RR>=2.0 -> 10 bps.
    """
    if not steps: return base_offset_bps
    factor = 1.0
    for s in steps:
        if rr >= s:
            # נשמור שזה מונוטוני — כל מדרגה לפחות 1.0×
            factor = max(factor, s)
    return max(1, int(round(base_offset_bps * factor)))

def _merge_targets_if_close(targets: List[float], splits: List[float], tick: float, side: str, band_ticks: int) -> Tuple[List[float], List[float], List[str]]:
    """
    אם שני יעדים קרובים <= band_ticks — מאחדים:
      * LONG: נבחר את המחיר היותר קרוב לשוק (נמוך יותר) כדי לשפר סיכוי מילוי.
      * SHORT: נבחר מחיר קרוב לשוק (גבוה יותר).
    מחזיר (targets_new, splits_new, notes) עם רשימת פעולות מיזוג לבקרה.
    """
    if band_ticks <= 0 or len(targets) <= 1:
        return targets, splits, []

    notes: List[str] = []
    out_t: List[float] = []
    out_s: List[float] = []

    i = 0
    while i < len(targets):
        if i < len(targets) - 1 and _ticks_between(targets[i], targets[i+1], tick) <= band_ticks:
            # merge i and i+1
            if side == "BUY":
                chosen = min(targets[i], targets[i+1])  # קרוב יותר למחיר כדי שיתמלא
            else:
                chosen = max(targets[i], targets[i+1])
            merged_split = splits[i] + splits[i+1]
            notes.append(f"merge TP{i+1}&TP{i+2} -> price={chosen}")
            out_t.append(chosen)
            out_s.append(merged_split)
            i += 2
        else:
            out_t.append(targets[i])
            out_s.append(splits[i])
            i += 1

    # נוודא שסכום splits נשאר 1.0 (תיקון זניח לפלואט)
    ssum = sum(out_s)
    if 0.99 <= ssum <= 1.01 and ssum != 1.0:
        out_s = [x / ssum for x in out_s]
    return out_t, out_s, notes

async def manage_once(
    symbol: Optional[str] = None,
    offset_bps: Optional[int] = None,
    pcts: Optional[List[float]] = None,
    splits: Optional[List[float]] = None,
    atr_mult: Optional[float] = None,
) -> Dict[str, Any]:
    """
    BE@entry (עם Stair פרוגרסיבי לפי RR) -> SL, TP ladder (עם Merge/Rearm), Trail לפי ATR*mult (אופציונלי).
    """
    # Binance client
    try:
        from binance.client import Client  # type: ignore
    except Exception as e:
        return {"ok": True, "delegated": False, "skipped": True, "reason": "binance_client_import_failed", "detail": str(e)}

    api_key = os.getenv("BINANCE_API_KEY", "").strip()
    api_sec = os.getenv("BINANCE_API_SECRET", "").strip()
    if not (api_key and api_sec):
        return {"ok": True, "delegated": False, "skipped": True, "reason": "binance_keys_missing"}

    if not symbol:
        return {"ok": False, "error": "missing symbol"}

    symbol = symbol.upper().strip()
    client = Client(api_key, api_sec)
    _align_position_mode(client)

    # Detect open position
    pos_amt = 0.0
    entry_price = None
    side_txt = None
    position_side = None  # CRITICAL: Track positionSide for Hedge Mode compatibility
    with suppress(Exception):
        positions = client.futures_position_information(symbol=symbol)
        for p in positions or []:
            amt = float(p.get("positionAmt") or 0.0)
            if abs(amt) > 0:
                pos_amt = amt
                entry_price = float(p.get("entryPrice") or 0.0)
                side_txt = "BUY" if amt > 0 else "SELL"
                position_side = p.get("positionSide")  # LONG/SHORT/BOTH (hedge mode)
                break
    if not side_txt or not entry_price or abs(pos_amt) <= 0:
        return {"ok": True, "skipped": True, "reason": "no_open_position"}

    tick, step = _get_filters(client, symbol)

    # Last price (fallback entry)
    price_now = entry_price
    with suppress(Exception):
        t = client.futures_symbol_ticker(symbol=symbol)
        if t and "price" in t:
            price_now = float(t["price"]) or entry_price
    base_price = price_now or entry_price

    # Recent OHLC לקביעת bounce קרוב
    kl_1m: Any = []
    with suppress(Exception):
        kl_1m = client.futures_klines(symbol=symbol, interval="1m", limit=30)

    ind = _ind_from_kl(kl_1m or [], period=14)
    atr = float(ind.get("atr") or 0.0)
    adx = float(ind.get("adx") or 0.0)

    # Defaults
    _offset_bps = int(offset_bps if isinstance(offset_bps, int) else BE_BASE_BPS)
    _pcts  = list(pcts) if pcts else [4.0, 8.0, 16.0]
    _splits= list(splits) if splits else [0.30, 0.30, 0.40]
    _atr_mult = float(atr_mult) if (atr_mult is not None) else None

    # Validate ladders
    if len(_pcts) != len(_splits):
        return {"ok": False, "error": "pcts/splits length mismatch"}
    if not (0.999 <= sum(_splits) <= 1.001):
        return {"ok": False, "error": "splits must sum to 1.0"}
    if any(x <= 0 for x in _pcts) or any(x <= 0 for x in _splits):
        return {"ok": False, "error": "pcts/splits must be > 0"}

    # 🔍 CRITICAL: Try to read original trade parameters from DB first
    db_params = _get_trade_params_from_db(symbol)
    original_sl = db_params.get("sl") if db_params else None
    original_tp = db_params.get("tp") if db_params else None
    
    if db_params:
        logger.debug(f"📊 {symbol}: Found DB params - SL={original_sl}, TP={original_tp}")
    
    # --- BE-Stair & Profit-Lock ---
    current_rr = _profit_rr(entry=float(entry_price), price_now=base_price, be_bps=_offset_bps, side=side_txt)
    stair_offset_bps = _apply_profit_lock(_offset_bps, current_rr, PROFIT_LOCK_STEPS)

    # Calculate BE Stop (Reduce risk), עם offset משודרג
    # CRITICAL: Use original SL from DB if available, otherwise calculate
    if original_sl and original_sl > 0:
        be_price = float(original_sl)
        logger.info(f"✅ {symbol}: Using original SL from DB: {be_price}")
    elif side_txt == "BUY":
        be_price = float(entry_price) * (1.0 - (stair_offset_bps / 10_000.0))
        be_price = _round_tick_dir(be_price, tick, "down")
        if base_price and be_price >= base_price:
            be_price = _bn_round(base_price - tick, tick)
    else:
        be_price = float(entry_price) * (1.0 + (stair_offset_bps / 10_000.0))
        be_price = _round_tick_dir(be_price, tick, "up")
        if base_price and be_price <= base_price:
            be_price = _round_tick_dir(base_price + tick, tick, "up")

    # Cancel existing SL/Trail AND TP orders to avoid conflicts
    # CRITICAL: Only cancel orders matching our positionSide (Hedge Mode compatibility)
    try:
        open_orders = client.futures_get_open_orders(symbol=symbol)
        cancelled_sl_count = 0
        cancelled_tp_count = 0
        skipped_count = 0
        for o in open_orders or []:
            t = str(o.get("type") or "")
            reduce_only = bool(o.get("reduceOnly"))
            order_position_side = o.get("positionSide")
            
            # SAFETY: Skip orders for opposite hedge leg
            if position_side and order_position_side and position_side != order_position_side:
                skipped_count += 1
                continue
            
            # Cancel SL/Trail orders (also closePosition=true orders without reduceOnly flag)
            if t in ("STOP", "STOP_MARKET", "TRAILING_STOP_MARKET") or bool(o.get("closePosition")):
                try:
                    client.futures_cancel_order(symbol=symbol, orderId=o.get("orderId"))
                    cancelled_sl_count += 1
                except Exception as e:
                    logger.warning(f"Failed to cancel old SL for {symbol}: {e}")
            # Cancel ALL types of TP orders (LIMIT, TAKE_PROFIT, TAKE_PROFIT_MARKET with reduceOnly)
            elif t in ("LIMIT", "TAKE_PROFIT", "TAKE_PROFIT_MARKET") and reduce_only:
                try:
                    client.futures_cancel_order(symbol=symbol, orderId=o.get("orderId"))
                    cancelled_tp_count += 1
                except Exception as e:
                    logger.warning(f"Failed to cancel old TP for {symbol}: {e}")
        if skipped_count > 0:
            logger.debug(f"Skipped {skipped_count} order(s) for opposite hedge leg ({symbol})")
        if cancelled_sl_count > 0:
            logger.info(f"Cancelled {cancelled_sl_count} old SL order(s) for {symbol} ({position_side or 'ONE-WAY'})")
        if cancelled_tp_count > 0:
            logger.info(f"Cancelled {cancelled_tp_count} old TP order(s) for {symbol} ({position_side or 'ONE-WAY'})")
    except Exception as e:
        logger.error(f"Failed to get/cancel old SL/TP for {symbol}: {e}")

    # Create/Replace BE Stop (STOP_MARKET closePosition)
    sl_placed = False
    
    # 🛡️ CRITICAL FIX: Skip SL placement if be_price is invalid (0 or negative)
    if be_price <= 0:
        logger.warning(f"⚠️ {symbol}: Skipping SL placement - invalid be_price={be_price} (entry={entry_price})")
        # Don't fail the whole operation - Fills Watcher might have already set SL
        sl_placed = False  # Continue with TP placement
    else:
        try:
            sl_kwargs = dict(
                symbol=symbol,
                side=("SELL" if side_txt == "BUY" else "BUY"),
                type="STOP_MARKET",
                stopPrice=be_price,
                closePosition=True,
                workingType=BINANCE_WORKING,
                newClientOrderId=_coid(symbol, ("SELL" if side_txt == "BUY" else "BUY"), role=f"SL@BE{stair_offset_bps}"),
            )
            
            # ✅ SMART POSITION MODE COMPATIBILITY
            # Add positionSide ONLY in Hedge Mode (LONG/SHORT)
            # In One-Way Mode, position_side='BOTH' and must be OMITTED
            if position_side and position_side in ("LONG", "SHORT"):
                sl_kwargs["positionSide"] = position_side
            
            sl_order = client.futures_create_order(**sl_kwargs)
            sl_placed = True
            logger.info(f"✅ {symbol}: SL placed @ {be_price} (Order #{sl_order.get('orderId')})")
        except Exception as e:
            logger.error(f"❌ CRITICAL: Failed to place SL for {symbol} @ {be_price}: {e}", exc_info=True)
            return {"ok": False, "error": f"SL placement failed: {str(e)}", "symbol": symbol}

    # --- TP ladder + Merge ---
    qty_abs = abs(pos_amt)
    raw_targets: List[float] = []
    for pct in _pcts:
        if side_txt == "BUY":
            px = base_price * (1.0 + pct / 100.0)
            px = _round_tick_dir(px, tick, "down")
        else:
            px = base_price * (1.0 - pct / 100.0)
            px = _round_tick_dir(px, tick, "up")
        raw_targets.append(px)

    targets, splits_used, merge_notes = _merge_targets_if_close(raw_targets, _splits, tick, side_txt, TP_MERGE_TICK_BAND)

    # Calculate quantities - last TP gets exact remainder to avoid ReduceOnly rejection
    tp_quantities: List[float] = []
    qty_sum = 0.0
    for i, split in enumerate(splits_used):
        if i == len(splits_used) - 1:
            # Last TP: exact remainder (rounded to step)
            qty_i = _bn_round(qty_abs - qty_sum, step)
        else:
            # Regular TPs: round down
            qty_i = _bn_round(qty_abs * float(split), step)
            qty_sum += qty_i
        tp_quantities.append(qty_i)

    placed_tp: List[Dict[str, Any]] = []
    for i, (tp_price, qty_i) in enumerate(zip(targets, tp_quantities), start=1):
        if qty_i <= 0: 
            logger.warning(f"Skipping TP{i} - calculated qty={qty_i} is invalid")
            continue
        
        # HYBRID TP Strategy: TP1=TAKE_PROFIT_MARKET (fast), TP2+=LIMIT (precise)
        if i == 1:
            # TP1: TAKE_PROFIT_MARKET for instant execution
            tp_kwargs = dict(
                symbol=symbol,
                side=("SELL" if side_txt == "BUY" else "BUY"),
                type="TAKE_PROFIT_MARKET",
                stopPrice=tp_price,
                quantity=qty_i,
                reduceOnly=True,
                newClientOrderId=_coid(symbol, ("SELL" if side_txt == "BUY" else "BUY"), role=f"TP{i}"),
            )
        else:
            # TP2+: LIMIT for precise price control
            tp_kwargs = dict(
                symbol=symbol,
                side=("SELL" if side_txt == "BUY" else "BUY"),
                type="LIMIT",
                price=tp_price,
                quantity=qty_i,
                timeInForce="GTC",
                reduceOnly=True,
                newClientOrderId=_coid(symbol, ("SELL" if side_txt == "BUY" else "BUY"), role=f"TP{i}"),
            )
        
        # ✅ SMART POSITION MODE COMPATIBILITY
        # Add positionSide ONLY in Hedge Mode (LONG/SHORT)
        # In One-Way Mode, position_side='BOTH' and must be OMITTED
        if position_side and position_side in ("LONG", "SHORT"):
            tp_kwargs["positionSide"] = position_side
        
        try:
            tp_order = client.futures_create_order(**tp_kwargs)
            placed_tp.append({"i": i, "price": tp_price, "qty": qty_i})
            tp_type = "TAKE_PROFIT_MARKET" if i == 1 else "LIMIT"
            logger.info(f"  ✅ TP{i} @ {tp_price} (qty: {qty_i}, type: {tp_type})")
        except Exception as e:
            logger.warning(f"Failed to place TP{i} for {symbol} @ {tp_price} qty={qty_i}: {e}")

    # --- Rearm on Bounce (כמעט נגיעה) ---
    # נבדוק high/low אחרונים אל מול היעד; אם קרוב בתוך TP_REARM_TICK — נזיז את ההזמנה טיק אחד פנימה לטובת מילוי.
    with suppress(Exception):
        if kl_1m:
            last_h = float(kl_1m[-1][2])
            last_l = float(kl_1m[-1][3])
            # נקרא שוב את ההזמנות הפתוחות כדי לאתר את ה-TPים
            oos = client.futures_get_open_orders(symbol=symbol) or []
            for o in oos:
                if o.get("type") == "LIMIT" and bool(o.get("reduceOnly")):
                    px = float(o.get("price") or 0.0)
                    oid = o.get("orderId")
                    if side_txt == "BUY":
                        # יעד למעלה: אם ה-high היה קרוב מספיק אבל לא מילא — נקרב טיק אחד מטה
                        if _ticks_between(last_h, px, tick) <= TP_REARM_TICK and last_h < px:
                            new_px = _bn_round(max(px - tick, tick), tick)
                            client.futures_cancel_order(symbol=symbol, orderId=oid)
                            with suppress(Exception):
                                client.futures_create_order(
                                    symbol=symbol,
                                    side="SELL",
                                    type="LIMIT",
                                    price=new_px,
                                    quantity=float(o.get("origQty")),
                                    timeInForce="GTC",
                                    reduceOnly=True,
                                    newClientOrderId=_coid(symbol, "SELL", role="TP_REARM"),
                                )
                    else:
                        # יעד למטה: אם ה-low היה קרוב מספיק אבל לא מילא — נקרב טיק אחד מעלה
                        if _ticks_between(last_l, px, tick) <= TP_REARM_TICK and last_l > px:
                            new_px = _round_tick_dir(px + tick, tick, "up")
                            client.futures_cancel_order(symbol=symbol, orderId=oid)
                            with suppress(Exception):
                                client.futures_create_order(
                                    symbol=symbol,
                                    side="BUY",
                                    type="LIMIT",
                                    price=new_px,
                                    quantity=float(o.get("origQty")),
                                    timeInForce="GTC",
                                    reduceOnly=True,
                                    newClientOrderId=_coid(symbol, "BUY", role="TP_REARM"),
                                )

    # --- ATR-based Trailing (optional) ---
    placed_trail = None
    if _atr_mult is not None:
        px = base_price or 0.0
        if px > 0:
            cb = (atr * float(_atr_mult) / px) * 100.0  # %
            binance_min_cb = 0.1
            cb = max(binance_min_cb, max(TRAIL_MIN_PCT, min(TRAIL_MAX_PCT, cb)))
            cb = round(cb, 1)
            with suppress(Exception):
                client.futures_create_order(
                    symbol=symbol,
                    side=("SELL" if side_txt == "BUY" else "BUY"),
                    type="TRAILING_STOP_MARKET",
                    callbackRate=cb,
                    reduceOnly=True,
                    workingType=BINANCE_WORKING,
                    newClientOrderId=_coid(symbol, ("SELL" if side_txt == "BUY" else "BUY"), role="TRAIL"),
                )
                placed_trail = {"callbackRate": cb}

    return {
        "ok": True,
        "delegated": False,
        "symbol": symbol,
        "side": side_txt,
        "entry": float(entry_price),
        "price_now": float(base_price),
        "be_stop_price": float(be_price),
        "be_base_bps": int(_offset_bps),
        "be_stair_bps": int(stair_offset_bps),
        "rr_now": round(current_rr, 2),
        "tp": placed_tp,
        "tp_merge_notes": merge_notes or None,
        "trail": placed_trail,
        "profile": {
            "name": "PLUS",
            "pcts": [float(x) for x in _pcts],
            "splits": [float(x) for x in _splits],
            "atr_mult": (_atr_mult if _atr_mult is not None else None),
            "profit_lock_steps": PROFIT_LOCK_STEPS,
            "tp_merge_tick_band": TP_MERGE_TICK_BAND,
            "tp_rearm_tick": TP_REARM_TICK,
        },
        "indicators": {
            "adx": round(adx, 2),
            "atr": float(atr),
            "atr_pct": (float(atr) / float(base_price)) if base_price else 0.0,
        },
    }
