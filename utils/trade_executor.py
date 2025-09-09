# utils/trade_executor.py
from __future__ import annotations
import math, logging, os
from typing import Optional, Dict, Any, List, Tuple

from utils.binance_client import (
    get_price, futures_mark_price, set_leverage, futures_create_order,
    get_symbol_filters
)

log = logging.getLogger("algogpt.trade_executor")

# מדיניות ברירת מחדל
ALLOW_MARKET_ENTRY = os.getenv("ALLOW_MARKET_ENTRY", "1") in ("1","true","yes","on")
# Offset קטן למחיר ההגבלה ב-STOP/TP כדי לשפר סיכוי להתמלאות (ב־bps):
SL_LIMIT_OFFSET_BPS = float(os.getenv("SL_LIMIT_OFFSET_BPS", "8"))     # 0.08%
TP_LIMIT_OFFSET_BPS = float(os.getenv("TP_LIMIT_OFFSET_BPS", "8"))

DEFAULT_QTY_STEP = float(os.getenv("DEFAULT_QTY_STEP", "0.001"))
DEFAULT_TICK     = float(os.getenv("DEFAULT_PRICE_TICK", "0.01"))
DEFAULT_MIN_NOT  = float(os.getenv("MIN_NOTIONAL_USDT", "5"))

def _round_step(x: float, step: float) -> float:
    if step <= 0: return x
    return math.floor(x / step) * step

def _decimals(step_str: str) -> int:
    if "." not in step_str: return 0
    frac = step_str.split(".")[1].rstrip("0")
    return len(frac)

def _q_price(symbol: str, price: float) -> Tuple[str, float]:
    f = get_symbol_filters(symbol) or {}
    tick = float(f.get("tickSize") or DEFAULT_TICK) or DEFAULT_TICK
    decs = _decimals(str(f.get("tickSize") or DEFAULT_TICK))
    steps = round(price / tick)
    p = steps * tick
    return (f"{p:.{decs}f}", float(f"{p:.{decs}f}"))

def _q_qty(symbol: str, qty: float) -> Tuple[str, float]:
    f = get_symbol_filters(symbol) or {}
    step = float(f.get("stepSize") or DEFAULT_QTY_STEP) or DEFAULT_QTY_STEP
    decs = _decimals(str(f.get("stepSize") or DEFAULT_QTY_STEP))
    steps = math.floor(qty / step)
    q = max(step, steps * step)
    return (f"{q:.{decs}f}", float(f"{q:.{decs}f}"))

def _min_notional(symbol: str) -> float:
    f = get_symbol_filters(symbol) or {}
    mn = f.get("minNotional")
    try: return float(mn) if mn is not None else DEFAULT_MIN_NOT
    except Exception: return DEFAULT_MIN_NOT

def _ensure_min_notional(symbol: str, price: float, qty: float) -> float:
    mn = _min_notional(symbol)
    if price * qty >= mn: return qty
    need = mn / max(price, 1e-12)
    _, q2 = _q_qty(symbol, need)
    return q2

def _calc_qty(symbol: str, price: float, *, budget: Optional[float], leverage: int, quantity: Optional[float]) -> float:
    if quantity and quantity > 0:
        q = float(quantity)
    else:
        if not budget or budget <= 0:
            raise ValueError("Either positive budget or quantity must be provided")
        usd = float(budget) * float(leverage)
        q = usd / price
    q = _ensure_min_notional(symbol, price, q)
    _, q = _q_qty(symbol, q)
    return q

def _entry_type(side: str, cur_price: float, entry: float) -> str:
    """
    Decide between LIMIT vs STOP (STOP_LIMIT) for entry:
    BUY  below cur => LIMIT; above => STOP
    SELL above cur => LIMIT; below => STOP
    """
    eps = cur_price * 0.0005  # 5bps סבילות
    if side == "BUY":
        return "LIMIT" if entry <= cur_price - eps else "STOP"
    else:
        return "LIMIT" if entry >= cur_price + eps else "STOP"

def _offset(price: float, bps: float, side: str, kind: str) -> float:
    """
    עבור SL/TP limit price מול stopPrice:
    - SL ללונג: רוצים מחיר מגמתי למטה; לשורט – למעלה.
    - TP ללונג: למעלה; לשורט – למטה.
    """
    sgn = 1.0
    if kind == "SL":
        sgn = -1.0 if side == "BUY" else 1.0
        return price * (1.0 + sgn * (bps/10000.0))
    elif kind == "TP":
        sgn = 1.0 if side == "BUY" else -1.0
        return price * (1.0 + sgn * (bps/10000.0))
    return price

async def execute_trade_live(
    symbol: str,
    side: str,
    *,
    budget: Optional[float] = None,
    leverage: int = 5,
    dry_run: bool = True,
    quantity: Optional[float] = None,
    # entry/targets:
    entry: Optional[float] = None,
    sl: Optional[float] = None,
    tp: Optional[float] = None,
    tp_targets: Optional[List[float]] = None,
    tp_splits: Optional[List[float]] = None,
    sl_targets: Optional[List[float]] = None,
    sl_splits: Optional[List[float]] = None,
) -> Dict[str, Any]:
    """
    טרייד מלא: כניסה + SL/TP (כולל ladders) ב-LIMIT/STOP בלבד.
    - אם entry לא סופק: כניסה MARKET (אם ALLOW_MARKET_ENTRY=1) אחרת LIMIT במחיר נוכחי.
    - SL/TP נשלחים כ-STOP/TAKE_PROFIT (limit), reduceOnly=True, עם סכומי כמות בהתאם ל-splits.
    """
    side = side.upper().strip()
    if side not in {"BUY", "SELL"}:
        raise ValueError("side must be BUY/SELL")
    sym = symbol.upper().strip()

    # מחיר נוכחי
    price = get_price(sym) or futures_mark_price(sym)
    if not price or price <= 0:
        raise RuntimeError(f"Cannot fetch price for {sym}")

    # כמות
    qty = _calc_qty(sym, price, budget=budget, leverage=leverage, quantity=quantity)

    # הכנה לרספונס
    plan: Dict[str, Any] = {
        "ok": True,
        "symbol": sym, "side": side,
        "leverage": leverage, "base_price": price, "qty": qty,
        "dry_run": dry_run,
        "entry_order": None, "tp_orders": [], "sl_orders": [],
    }

    # חישוב כניסה
    entry_kind = "MARKET"
    entry_price = price
    if entry is not None:
        entry_kind = _entry_type(side, price, float(entry))
        entry_price = float(entry)
    elif not ALLOW_MARKET_ENTRY:
        entry_kind = "LIMIT"
        entry_price = price  # LIMIT סביב המחיר

    # כימות מחיר כניסה (במידה ורלוונטי)
    q_entry_price_str, q_entry_price = _q_price(sym, entry_price)

    # Dry-run יציב לפני שליחה
    def _append_tp(price_list: List[float], splits: Optional[List[float]]):
        nonlocal plan
        if not price_list:
            return
        L = len(price_list)
        weights = splits or []
        if not weights or len(weights) != L:
            # חלוקה אוטומטית: שווה בכל היעדים, האחרון סוגר יתרה אם צריך
            weights = [1.0 / L] * L
        # נוודא שסכום ≤ 1.0
        total = sum(max(0.0, float(x)) for x in weights)
        if total <= 0:
            weights = [1.0 / L] * L
            total = 1.0
        # כמות לרמות, האחרונה סוגרת יתרה
        remain = qty
        for i, (p_raw, w) in enumerate(zip(price_list, weights), start=1):
            alloc = qty * (float(w) / total) if i < L else remain
            _, q_alloc = _q_qty(sym, max(0.0, alloc))
            if q_alloc <= 0:
                continue
            remain = max(0.0, remain - q_alloc)
            # limit price סביב ה-stopPrice
            limit_p = _offset(float(p_raw), TP_LIMIT_OFFSET_BPS, side, "TP")
            q_stop_str, q_stop = _q_price(sym, float(p_raw))
            q_lim_str , q_lim  = _q_price(sym, float(limit_p))
            plan["tp_orders"].append({
                "type": "TAKE_PROFIT", "stopPrice": q_stop, "price": q_lim, "qty": q_alloc
            })

    def _append_sl(price_list: List[float], splits: Optional[List[float]]):
        nonlocal plan
        if not price_list:
            return
        L = len(price_list)
        weights = splits or []
        if not weights or len(weights) != L:
            weights = [1.0 / L] * L
        total = sum(max(0.0, float(x)) for x in weights)
        if total <= 0:
            weights = [1.0 / L] * L
            total = 1.0
        remain = qty
        for i, (p_raw, w) in enumerate(zip(price_list, weights), start=1):
            alloc = qty * (float(w) / total) if i < L else remain
            _, q_alloc = _q_qty(sym, max(0.0, alloc))
            if q_alloc <= 0:
                continue
            remain = max(0.0, remain - q_alloc)
            limit_p = _offset(float(p_raw), SL_LIMIT_OFFSET_BPS, side, "SL")
            q_stop_str, q_stop = _q_price(sym, float(p_raw))
            q_lim_str , q_lim  = _q_price(sym, float(limit_p))
            plan["sl_orders"].append({
                "type": "STOP", "stopPrice": q_stop, "price": q_lim, "qty": q_alloc
            })

    # לבנות TP/SL מהקלט
    if tp is not None:
        _append_tp([float(tp)], None)
    if sl is not None:
        _append_sl([float(sl)], None)
    if tp_targets:
        _append_tp([float(x) for x in tp_targets], tp_splits)
    if sl_targets:
        _append_sl([float(x) for x in sl_targets], sl_splits)

    # בניית הזמנת כניסה בתוכנית
    plan["entry_order"] = {
        "kind": entry_kind,
        "price": q_entry_price if entry_kind != "MARKET" else None,
        "qty": qty,
    }

    if dry_run:
        return plan

    # ───────────────────────────────────────────────────────────────────
    # ביצוע אמיתי
    # ───────────────────────────────────────────────────────────────────
    # מינוף
    try:
        set_leverage(sym, int(leverage))
    except Exception as e:
        log.warning("set_leverage failed: %s", e)

    # שליחת כניסה
    entry_resp: Dict[str, Any]
    if entry_kind == "MARKET":
        entry_resp = futures_create_order(
            symbol=sym, side=side, type="MARKET", quantity=_q_qty(sym, qty)[0]
        )
    elif entry_kind == "LIMIT":
        entry_resp = futures_create_order(
            symbol=sym, side=side, type="LIMIT",
            timeInForce="GTC", price=_q_price(sym, q_entry_price)[0],
            quantity=_q_qty(sym, qty)[0]
        )
    else:  # STOP (כלומר STOP_LIMIT for entry)
        # בפיוצ׳רס: type="STOP" עם stopPrice + price (limit)
        stop_str, stop_p = _q_price(sym, q_entry_price)
        lim_str , lim_p  = _q_price(sym, q_entry_price)  # אפשר להזיז מעט אם תרצה
        entry_resp = futures_create_order(
            symbol=sym, side=side, type="STOP",
            timeInForce="GTC", stopPrice=stop_str, price=lim_str,
            quantity=_q_qty(sym, qty)[0]
        )
    plan["entry_order"]["response"] = entry_resp

    # שליחת TP/SL כ-reduceOnly LIMIT stops
    # הערה: ב-Binance FUTURES, LIMIT variants (STOP/TAKE_PROFIT) לא מאפשרים closePosition=True,
    # לכן נשתמש ב-quantity + reduceOnly=True לכל רמה.
    for tpo in plan["tp_orders"]:
        try:
            resp = futures_create_order(
                symbol=sym, side=("SELL" if side == "BUY" else "BUY"),
                type="TAKE_PROFIT",  # LIMIT variant
                timeInForce="GTC",
                reduceOnly=True,
                stopPrice=_q_price(sym, float(tpo["stopPrice"]))[0],
                price=_q_price(sym, float(tpo["price"]))[0],
                quantity=_q_qty(sym, float(tpo["qty"]))[0],
            )
            tpo["response"] = resp
        except Exception as e:
            tpo["response"] = {"ok": False, "error": str(e)}

    for slo in plan["sl_orders"]:
        try:
            resp = futures_create_order(
                symbol=sym, side=("SELL" if side == "BUY" else "BUY"),
                type="STOP",  # LIMIT variant
                timeInForce="GTC",
                reduceOnly=True,
                stopPrice=_q_price(sym, float(slo["stopPrice"]))[0],
                price=_q_price(sym, float(slo["price"]))[0],
                quantity=_q_qty(sym, float(slo["qty"]))[0],
            )
            slo["response"] = resp
        except Exception as e:
            slo["response"] = {"ok": False, "error": str(e)}

    return plan
































































