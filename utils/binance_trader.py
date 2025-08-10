# utils/binance_trader.py
import math
import time
import random
import logging
from typing import Dict, Any, Optional

import requests

from utils import config
from utils.binance_client import get_client, futures_exchange_info_safe
try:
    # עטיפת ריטריי הרשמית
    from utils.binance_client import retry_call
except Exception:
    # תאימות לאחור אם השם הפרטי הישן קיים
    from utils.binance_client import _retry_call as retry_call  # type: ignore

_client = get_client()

# ===== פרמטרי רשת/ריטריי/חתימות =====
_FAPI_HTTP   = getattr(config, "BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com")
_BACKOFF_BASE = float(getattr(config, "BINANCE_BACKOFF_BASE", 0.7))
_MAX_RETRIES  = int(getattr(config, "BINANCE_MAX_RETRIES", 5))
_RECV_WINDOW  = int(getattr(config, "BINANCE_RECV_WINDOW", 10000))

# אפשרות לכפות Hedge Mode דרך קונפיג (ברירת מחדל: None → זיהוי אוטומטי)
_FORCE_HEDGE_MODE = getattr(config, "BINANCE_FORCE_HEDGE_MODE", None)  # True/False/None
_HEDGE_MODE_CACHE: Optional[bool] = None

# ניתן להשבית שינויי חשבון (לברג'/מרג'ין) כאשר יש WAF/403 עד ש־egress מאושר
_SKIP_MUTATIONS = bool(getattr(config, "BINANCE_SKIP_ACCOUNT_MUTATIONS", False))

# סשן עצמאי לפולבקי REST (exchangeInfo per-symbol)
_session = requests.Session()
_session.trust_env = False
_session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Encoding": "gzip",
    "Accept-Language": "en-US,en;q=0.9",
})

# Cache לפילטרים לכל סימבול
_SYMBOL_FILTERS_CACHE: dict[str, dict] = {}

def _to_float(x, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return float(default)

def _floor_to_step(value: float, step: float, precision: int = 8) -> float:
    step = float(step)
    if step <= 0:
        return round(value, precision)
    return round(math.floor(float(value) / step) * step, precision)

def _ceil_to_step(value: float, step: float, precision: int = 8) -> float:
    step = float(step)
    if step <= 0:
        return round(value, precision)
    return round(math.ceil(float(value) / step) * step, precision)

def _round_to_tick(value: float, tick: float) -> float:
    tick = float(tick or 0.0001)
    if tick <= 0:
        tick = 0.0001
    return round(round(value / tick) * tick, 8)

def _http_exchange_info_symbol(sym: str, timeout: float = 8.0) -> Optional[dict]:
    """
    קריאה ישירה ל-/fapi/v1/exchangeInfo?symbol=SYMBOL עם ריטריי.
    מחזיר meta של הסימבול מתוך "symbols".
    """
    url = f"{_FAPI_HTTP}/fapi/v1/exchangeInfo"
    params = {"symbol": sym.upper()}
    last = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            r = _session.get(url, params=params, timeout=timeout)
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, dict) and isinstance(data.get("symbols"), list) and data["symbols"]:
                    return data["symbols"][0]
                if isinstance(data, dict) and isinstance(data.get("symbols"), list):
                    for s in data["symbols"]:
                        if s.get("symbol") == sym:
                            return s
                return None
            if r.status_code in (403, 418, 429, 503):
                d = min(10.0, _BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 0.35))
                logging.warning(f"[trader] exchangeInfo {sym} http={r.status_code} → sleep {d:.2f}s")
                time.sleep(d); last = r.text; continue
            r.raise_for_status()
        except Exception as e:
            d = min(10.0, _BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 0.35))
            logging.warning(f"[trader] exchangeInfo {sym} net err (attempt {attempt+1}/{_MAX_RETRIES+1}): {e} → {d:.2f}s")
            time.sleep(d); last = e; continue
    if last:
        logging.warning(f"[trader] exchangeInfo REST failed for {sym}: {last}")
    return None

def _guess_filters(sym: str) -> dict:
    """
    פולבק שמרני כשאין exchangeInfo (CloudFront/חסימה).
    """
    return {
        "tickSize": 0.01,     # עיגול מחיר לשתי ספרות
        "stepSize": 0.001,    # גודל צעד כמות
        "minQty": 0.001,      # כמינימום בסיסי
        "minNotional": 5.0,   # דרישת notional שמרנית
        "_source": "fallback"
    }

def _load_symbol_filters(symbol: str) -> dict:
    sym = str(symbol).upper()
    if sym in _SYMBOL_FILTERS_CACHE:
        return _SYMBOL_FILTERS_CACHE[sym]

    meta = _http_exchange_info_symbol(sym)
    if not meta:
        # נסיון דרך SDK (exchangeInfo מלא) — יקר יותר, אך אולי פתוח
        try:
            ei = futures_exchange_info_safe()
            if isinstance(ei, dict) and isinstance(ei.get("symbols"), list):
                meta = next((s for s in ei["symbols"] if s.get("symbol") == sym), None)
        except Exception as e:
            logging.debug(f"[trader] futures_exchange_info_safe error ignored: {e}")

    if meta:
        price_filter  = next((f for f in meta.get("filters", []) if f.get("filterType") == "PRICE_FILTER"), None)
        lot_filter    = next((f for f in meta.get("filters", []) if f.get("filterType") == "LOT_SIZE"), None)
        notional_filt = next((f for f in meta.get("filters", []) if f.get("filterType") in ("MIN_NOTIONAL", "NOTIONAL")), None)

        tick_size = _to_float(price_filter.get("tickSize") if price_filter else "0.0001", 0.0001)
        step_size = _to_float(lot_filter.get("stepSize") if lot_filter else "0.001", 0.001)
        min_qty   = _to_float(lot_filter.get("minQty")  if lot_filter else "0.0",    0.0)
        min_notional = 0.0
        if notional_filt:
            min_notional = _to_float(notional_filt.get("notional", notional_filt.get("minNotional", "0.0")), 0.0)

        out = {
            "tickSize": tick_size,
            "stepSize": step_size,
            "minQty": min_qty,
            "minNotional": min_notional or 5.0,
            "_source": "rest",
        }
        _SYMBOL_FILTERS_CACHE[sym] = out
        return out

    out = _guess_filters(sym)
    _SYMBOL_FILTERS_CACHE[sym] = out
    logging.warning(f"[trader] ⚠️ using fallback filters for {sym}: {out}")
    return out

def _compute_qty_by_budget(budget_usd: float, leverage: int, entry_price: float,
                           step_size: float, min_qty: float) -> float:
    notional = float(budget_usd) * int(leverage)
    if entry_price <= 0:
        raise ValueError("entry_price must be > 0")
    raw_qty = notional / float(entry_price)
    qty = _floor_to_step(raw_qty, step_size, precision=8)
    if qty < min_qty:
        qty = _ceil_to_step(min_qty, step_size, precision=8)
    return qty

def _ensure_notional(qty: float, price: float, min_notional: float) -> bool:
    return (float(qty) * float(price)) >= float(min_notional)

def _side_for_entry(direction: str) -> str:
    return "BUY" if (direction or "").upper() == "LONG" else "SELL"

def _side_for_exit(direction: str) -> str:
    return "SELL" if (direction or "").upper() == "LONG" else "BUY"

def _safe_leverage(l: int) -> int:
    l = int(l)
    max_lev = int(getattr(config, "MAX_LEVERAGE", 35))
    if l < 1: l = 1
    if l > max_lev: l = max_lev
    return l

def _detect_hedge_mode() -> bool:
    """
    מחזיר True אם החשבון במצב Hedge (dualSidePosition=True), אחרת False.
    מטמון בזיכרון כדי לא להעמיס.
    """
    global _HEDGE_MODE_CACHE
    if _FORCE_HEDGE_MODE is True:
        _HEDGE_MODE_CACHE = True
        return True
    if _FORCE_HEDGE_MODE is False:
        _HEDGE_MODE_CACHE = False
        return False
    if _HEDGE_MODE_CACHE is not None:
        return _HEDGE_MODE_CACHE
    try:
        data = retry_call(lambda: _client.futures_get_position_mode(recvWindow=_RECV_WINDOW), name="get_position_mode")
        is_hedge = bool(data.get("dualSidePosition"))
        _HEDGE_MODE_CACHE = is_hedge
        logging.info(f"[trader] position mode detected: {'HEDGE' if is_hedge else 'ONE-WAY'}")
        return is_hedge
    except Exception as e:
        logging.warning(f"[trader] cannot detect position mode, assuming ONE-WAY: {e}")
        _HEDGE_MODE_CACHE = False
        return False

def _apply_position_side(params: dict, direction: str, is_exit: bool, hedge: bool) -> dict:
    """
    אם במצב Hedge – נצרף positionSide תואם:
    LONG:  entry BUY  -> positionSide=LONG
           exit  SELL -> positionSide=LONG
    SHORT: entry SELL -> positionSide=SHORT
           exit  BUY  -> positionSide=SHORT
    """
    if not hedge:
        return params
    d = (direction or "").upper()
    pos_side = "LONG" if d == "LONG" else "SHORT"
    params = dict(params)
    params["positionSide"] = pos_side
    return params

def _place_with_recv(fn, name: str):
    """עוטף קריאת SDK (עם recvWindow) דרך retry_call."""
    return retry_call(lambda: fn(), name=name)

async def binance_futures_trade(
    symbol: str,
    side: str,            # "LONG" / "SHORT"
    entry: float,
    sl: float,
    tp: float,
    leverage: int = 20,
    budget: float = 100.0,
    quantity: Optional[float] = None,   # אם הועבר — נכבד אחרי עיגול ובדיקות
    market_type: str = "futures",
    margin_type: str = "ISOLATED",      # או "CROSSED"
) -> Dict[str, Any]:
    """
    ביצוע טרייד USDT-M Futures (One-Way או Hedge):
      - כניסה LIMIT (GTC)
      - SL/TP כ-STOP/TAKE_PROFIT (Limit) עם reduceOnly וב-Hedge גם positionSide
      - עיגול לפי tick/step, בדיקות minQty/minNotional
      - recvWindow=10000 לכל הקריאות החתומות
    """
    if market_type.lower() != "futures":
        raise ValueError("Only futures market_type is supported.")

    symbol = str(symbol).upper()
    direction = (side or "").upper()
    entry_price = float(entry)
    stop_price  = float(sl)
    take_profit = float(tp)
    lev = _safe_leverage(leverage)

    hedge_mode = _detect_hedge_mode()

    # פילטרים (עם REST+פולבק; בלי קריסה)
    filters = _load_symbol_filters(symbol)
    tick = float(filters["tickSize"])
    step = float(filters["stepSize"])
    min_qty = float(filters["minQty"])
    min_notional = float(filters["minNotional"])

    # שינוי מצב מרג'ין ולברג' (ניתן להשבית עם BINANCE_SKIP_ACCOUNT_MUTATIONS=true)
    if not _SKIP_MUTATIONS:
        try:
            _place_with_recv(lambda: _client.futures_change_margin_type(
                symbol=symbol, marginType=margin_type, recvWindow=_RECV_WINDOW
            ), "change_margin_type")
        except Exception as e:
            logging.debug(f"[trader] change_margin_type ignored: {e}")
        try:
            _place_with_recv(lambda: _client.futures_change_leverage(
                symbol=symbol, leverage=int(lev), recvWindow=_RECV_WINDOW
            ), "change_leverage")
        except Exception as e:
            logging.debug(f"[trader] change_leverage ignored: {e}")
    else:
        logging.info("[trader] 🔕 skipping account mutations (leverage/marginType) due to BINANCE_SKIP_ACCOUNT_MUTATIONS=true")

    # עיגול מחירים
    entry_p    = _round_to_tick(entry_price, tick)
    sl_trigger = _round_to_tick(stop_price, tick)
    tp_trigger = _round_to_tick(take_profit, tick)

    # מחירי limit עבור STOP/TP (שיתמלאו אחרי הטריגר)
    if direction == "LONG":
        sl_limit = _round_to_tick(max(sl_trigger - tick, tick), tick)
        tp_limit = _round_to_tick(min(tp_trigger + tick, tp_trigger * 1.002), tick)
    else:
        sl_limit = _round_to_tick(min(sl_trigger + tick, sl_trigger * 1.002), tick)
        tp_limit = _round_to_tick(max(tp_trigger - tick, tick), tick)

    # כמות
    if quantity is not None and quantity > 0:
        qty = float(quantity)
        qty = _floor_to_step(qty, step, precision=8)
        if qty < min_qty:
            qty = _ceil_to_step(min_qty, step, precision=8)
    else:
        qty = _compute_qty_by_budget(budget_usd=budget, leverage=lev, entry_price=entry_p, step_size=step, min_qty=min_qty)

    # בדיקת notional מינימלי — נרים כמות אם צריך
    if not _ensure_notional(qty, entry_p, min_notional):
        qty2 = _ceil_to_step(min_notional / entry_p, step, precision=8)
        if qty2 > qty:
            qty = qty2

    if qty < min_qty or qty <= 0:
        raise ValueError(f"Qty below minimum after rounding: qty={qty}, min_qty={min_qty}")

    entry_side = _side_for_entry(direction)
    exit_side  = _side_for_exit(direction)

    # jitter קטן לפני POST (מפחית 403/429/WAF)
    time.sleep(random.uniform(0.12, 0.35))

    # === LIMIT כניסה ===
    entry_params = dict(
        symbol=symbol,
        side=entry_side,
        type="LIMIT",
        timeInForce="GTC",
        quantity=qty,
        price=entry_p,
        reduceOnly=False,
        recvWindow=_RECV_WINDOW,
    )
    entry_params = _apply_position_side(entry_params, direction, is_exit=False, hedge=hedge_mode)

    entry_order = _place_with_recv(lambda: _client.futures_create_order(**entry_params), name="entry_LIMIT")
    if not isinstance(entry_order, dict) or "orderId" not in entry_order:
        raise RuntimeError(f"Failed to place entry order: {entry_order}")

    # === STOP-LIMIT (SL) ===
    sl_params = dict(
        symbol=symbol,
        side=exit_side,
        type="STOP",
        timeInForce="GTC",
        quantity=qty,
        stopPrice=sl_trigger,
        price=sl_limit,
        reduceOnly=True,
        workingType="CONTRACT_PRICE",
        recvWindow=_RECV_WINDOW,
    )
    sl_params = _apply_position_side(sl_params, direction, is_exit=True, hedge=hedge_mode)

    sl_order = _place_with_recv(lambda: _client.futures_create_order(**sl_params), name="stop_limit")
    if not isinstance(sl_order, dict) or "orderId" not in sl_order:
        raise RuntimeError(f"Failed to place STOP-LIMIT order: {sl_order}")

    # === TAKE_PROFIT-LIMIT (TP) ===
    tp_params = dict(
        symbol=symbol,
        side=exit_side,
        type="TAKE_PROFIT",
        timeInForce="GTC",
        quantity=qty,
        stopPrice=tp_trigger,
        price=tp_limit,
        reduceOnly=True,
        workingType="CONTRACT_PRICE",
        recvWindow=_RECV_WINDOW,
    )
    tp_params = _apply_position_side(tp_params, direction, is_exit=True, hedge=hedge_mode)

    tp_order = _place_with_recv(lambda: _client.futures_create_order(**tp_params), name="tp_limit")
    if not isinstance(tp_order, dict) or "orderId" not in tp_order:
        raise RuntimeError(f"Failed to place TP-LIMIT order: {tp_order}")

    return {
        "ok": True,
        "symbol": symbol,
        "direction": direction,
        "hedge_mode": bool(hedge_mode),
        "leverage": int(lev),
        "qty": float(qty),
        "entry": {"price": entry_p, "orderId": entry_order["orderId"], "clientOrderId": entry_order.get("clientOrderId")},
        "sl":    {"trigger": sl_trigger, "limit": sl_limit, "orderId": sl_order["orderId"]},
        "tp":    {"trigger": tp_trigger, "limit": tp_limit, "orderId": tp_order["orderId"]},
    }

# ---- API ציבורית לדיבוג פילטרים ----
def get_symbol_filters(symbol: str) -> dict:
    """פונקציה ציבורית להצגת פילטרים, כולל מקור (rest/fallback)."""
    return _load_symbol_filters(symbol)



















