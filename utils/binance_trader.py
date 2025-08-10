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
    # עדיף ייצוא רשמי
    from utils.binance_client import retry_call
except Exception:
    # תאימות לאחור אם השם הפרטי הישן קיים
    from utils.binance_client import _retry_call as retry_call  # type: ignore

_client = get_client()

# Cache לפילטרים לכל סימבול
_SYMBOL_FILTERS_CACHE: dict[str, dict] = {}

# ---- פרמטרי רשת/ריטריי ----
_FAPI_HTTP = getattr(config, "BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com")
_BACKOFF_BASE = float(getattr(config, "BINANCE_BACKOFF_BASE", 0.7))
_MAX_RETRIES = int(getattr(config, "BINANCE_MAX_RETRIES", 5))

_session = requests.Session()
_session.headers.update({
    "User-Agent": "AlgoGPT/2 (Render) binance-trader",
    "Accept": "application/json",
    "Accept-Encoding": "gzip",
})
if getattr(config, "BINANCE_API_KEY", ""):
    _session.headers.update({"X-MBX-APIKEY": config.BINANCE_API_KEY})

def _to_float(x, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return float(default)

def _floor_to_step(value: float, step: float, precision: int = 8) -> float:
    step = float(step)
    return round(math.floor(float(value) / step) * step, precision)

def _ceil_to_step(value: float, step: float, precision: int = 8) -> float:
    step = float(step)
    return round(math.ceil(float(value) / step) * step, precision)

def _round_to_tick(value: float, tick: float) -> float:
    tick = float(tick)
    return round(round(value / tick) * tick, 8)

def _http_exchange_info_symbol(sym: str, timeout: float = 8.0) -> Optional[dict]:
    """
    קריאה ישירה ל-/fapi/v1/exchangeInfo?symbol=SYMBOL עם ריטריי.
    מחזיר meta של הסימבול מתוך "symbols".
    """
    url = f"{_FAPI_HTTP}/fapi/v1/exchangeInfo"
    params = {"symbol": sym}
    last = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            r = _session.get(url, params=params, timeout=timeout)
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, dict) and isinstance(data.get("symbols"), list) and data["symbols"]:
                    return data["symbols"][0]
                # יש הטמעות שמחזירות אובייקט מלא בלי סינון; ננסה למצוא ידנית
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
    ניחוש שמרני כשאין exchangeInfo (CloudFront/חסימה).
    הערכים מספיקים לרוב הסימבולים הגדולים; אם ההזמנה תידחה ע״י הבורסה,
    המשתמש יראה שגיאה מפורטת בלוג ונוכל לחדד ידנית.
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

    # 1) נסה REST ישיר פר-סימבול
    meta = _http_exchange_info_symbol(sym)
    if not meta:
        # 2) נסה SDK (ייתכן שיעבוד בסביבה אחרת)
        try:
            ei = futures_exchange_info_safe()
            if isinstance(ei, dict) and isinstance(ei.get("symbols"), list):
                meta = next((s for s in ei["symbols"] if s.get("symbol") == sym), None)
        except Exception as e:
            logging.debug(f"[trader] futures_exchange_info_safe error ignored: {e}")

    if meta:
        price_filter = next((f for f in meta.get("filters", []) if f.get("filterType") == "PRICE_FILTER"), None)
        lot_filter   = next((f for f in meta.get("filters", []) if f.get("filterType") == "LOT_SIZE"), None)
        notion_filter = next((f for f in meta.get("filters", []) if f.get("filterType") in ("MIN_NOTIONAL", "NOTIONAL")), None)

        tick_size = _to_float(price_filter.get("tickSize") if price_filter else "0.0001", 0.0001)
        step_size = _to_float(lot_filter.get("stepSize") if lot_filter else "0.001", 0.001)
        min_qty = _to_float(lot_filter.get("minQty") if lot_filter else "0.0", 0.0)
        min_notional = 0.0
        if notion_filter:
            min_notional = _to_float(notion_filter.get("notional", notion_filter.get("minNotional", "0.0")), 0.0)

        out = {
            "tickSize": tick_size,
            "stepSize": step_size,
            "minQty": min_qty,
            "minNotional": min_notional or 5.0,
            "_source": "rest",
        }
        _SYMBOL_FILTERS_CACHE[sym] = out
        return out

    # 3) פולבק שמרני (לא מפילים ריצה)
    out = _guess_filters(sym)
    _SYMBOL_FILTERS_CACHE[sym] = out
    logging.warning(f"[trader] ⚠️ using fallback filters for {sym}: {out}")
    return out

def _compute_qty(budget_usd: float, leverage: int, entry_price: float, step_size: float, min_qty: float) -> float:
    notional = float(budget_usd) * int(leverage)
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

async def binance_futures_trade(
    symbol: str,
    side: str,            # "LONG" / "SHORT"
    entry: float,
    sl: float,
    tp: float,
    leverage: int = 20,
    budget: float = 100.0,
    market_type: str = "futures",
    margin_type: str = "ISOLATED",  # או "CROSSED"
) -> Dict[str, Any]:
    """
    ביצוע טרייד USDT-M Futures:
      - כניסה LIMIT (GTC) בלבד
      - SL/TP כ-STOP/TAKE_PROFIT (Limit) עם reduceOnly
      - עיגול לפי tick/step, בדיקות minQty/minNotional
    """
    if market_type.lower() != "futures":
        raise ValueError("Only futures market_type is supported.")

    symbol = str(symbol).upper()
    direction = (side or "").upper()
    entry_price = float(entry)
    stop_price = float(sl)
    take_profit = float(tp)

    # פילטרים (עם REST+פולבק; בלי קריסה)
    filters = _load_symbol_filters(symbol)
    tick = filters["tickSize"]
    step = filters["stepSize"]
    min_qty = filters["minQty"]
    min_notional = filters["minNotional"]

    # מינוף/מצב מרג'ין (לא מפיל אם נכשל)
    try:
        retry_call(lambda: _client.futures_change_margin_type(symbol=symbol, marginType=margin_type), name="change_margin_type")
    except Exception as e:
        logging.debug(f"[trader] change_margin_type ignored: {e}")
    try:
        retry_call(lambda: _client.futures_change_leverage(symbol=symbol, leverage=int(leverage)), name="change_leverage")
    except Exception as e:
        logging.debug(f"[trader] change_leverage ignored: {e}")

    # עיגול מחירים
    entry_p = _round_to_tick(entry_price, tick)
    sl_trigger = _round_to_tick(stop_price, tick)
    tp_trigger = _round_to_tick(take_profit, tick)

    # מחירי limit עבור ה-STOP/TP (שיתמלאו אחרי הטריגר)
    if direction == "LONG":
        sl_limit = _round_to_tick(max(sl_trigger - tick, tick), tick)
        tp_limit = _round_to_tick(min(tp_trigger + tick, tp_trigger * 1.002), tick)
    else:
        sl_limit = _round_to_tick(min(sl_trigger + tick, sl_trigger * 1.002), tick)
        tp_limit = _round_to_tick(max(tp_trigger - tick, tick), tick)

    # כמות
    qty = _compute_qty(budget_usd=budget, leverage=int(leverage), entry_price=entry_p, step_size=step, min_qty=min_qty)
    if not _ensure_notional(qty, entry_p, min_notional):
        qty2 = _ceil_to_step(min_notional / entry_p, step, precision=8)
        if qty2 > qty:
            qty = qty2
    if qty < min_qty or qty <= 0:
        raise ValueError(f"Qty below minimum after rounding: qty={qty}, min_qty={min_qty}")

    entry_side = _side_for_entry(direction)
    exit_side = _side_for_exit(direction)

    # LIMIT כניסה
    entry_order = retry_call(
        lambda: _client.futures_create_order(
            symbol=symbol,
            side=entry_side,
            type="LIMIT",
            timeInForce="GTC",
            quantity=qty,
            price=entry_p,
            reduceOnly=False
        ),
        name="entry_LIMIT"
    )
    if not isinstance(entry_order, dict) or "orderId" not in entry_order:
        raise RuntimeError(f"Failed to place entry order: {entry_order}")

    # STOP-LIMIT (SL)
    sl_order = retry_call(
        lambda: _client.futures_create_order(
            symbol=symbol,
            side=exit_side,
            type="STOP",
            timeInForce="GTC",
            quantity=qty,
            stopPrice=sl_trigger,
            price=sl_limit,
            reduceOnly=True,
            workingType="CONTRACT_PRICE"
        ),
        name="stop_limit"
    )
    if not isinstance(sl_order, dict) or "orderId" not in sl_order:
        raise RuntimeError(f"Failed to place STOP-LIMIT order: {sl_order}")

    # TAKE_PROFIT-LIMIT (TP)
    tp_order = retry_call(
        lambda: _client.futures_create_order(
            symbol=symbol,
            side=exit_side,
            type="TAKE_PROFIT",
            timeInForce="GTC",
            quantity=qty,
            stopPrice=tp_trigger,
            price=tp_limit,
            reduceOnly=True,
            workingType="CONTRACT_PRICE"
        ),
        name="tp_limit"
    )
    if not isinstance(tp_order, dict) or "orderId" not in tp_order:
        raise RuntimeError(f"Failed to place TP-LIMIT order: {tp_order}")

    return {
        "ok": True,
        "symbol": symbol,
        "direction": direction,
        "leverage": int(leverage),
        "qty": float(qty),
        "entry": {"price": entry_p, "orderId": entry_order["orderId"], "clientOrderId": entry_order.get("clientOrderId")},
        "sl":    {"trigger": sl_trigger, "limit": sl_limit, "orderId": sl_order["orderId"]},
        "tp":    {"trigger": tp_trigger, "limit": tp_limit, "orderId": tp_order["orderId"]},
    }

# ---- API ציבורית לדיבוג פילטרים ----
def get_symbol_filters(symbol: str) -> dict:
    """פונקציה ציבורית להצגת פילטרים, כולל מקור (rest/fallback)."""
    return _load_symbol_filters(symbol)


















