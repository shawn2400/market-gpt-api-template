# utils/trade_executor.py
import asyncio
import logging
import random
from decimal import Decimal, ROUND_FLOOR
from typing import Dict, Any, Optional, Tuple

from utils import config
from utils.ws_fallback import get_price_smart, is_price_fresh
from utils.binance_client import futures_exchange_info_safe
from utils.binance_trader import binance_futures_trade  # מניחים async ויציב

# ===== קונפיג עם ברירות מחדל בטוחות =====
PRICE_PROTECT_PCT: float = float(getattr(config, "PRICE_PROTECT_PCT", 0.25))
PRICE_MAX_AGE_SEC: int   = int(getattr(config, "PRICE_MAX_AGE_SEC", 10))
MAX_TRADE_RETRIES: int   = int(getattr(config, "TRADE_MAX_RETRIES", 2))
BACKOFF_BASE: float      = float(getattr(config, "TRADE_BACKOFF_BASE", 0.7))
MAX_LEVERAGE: int        = int(getattr(config, "MAX_LEVERAGE", 35))  # שמרני: 5–35
MIN_LEVERAGE: int        = 1

# ===== Cache לפילטרים מהבורסה =====
_SYMBOL_FILTERS: Dict[str, Dict[str, str]] = {}
_FILTERS_LOADED: bool = False

def _norm_direction(d: str) -> str:
    d = (d or "").strip().upper()
    if d in ("LONG", "BUY"):
        return "LONG"
    if d in ("SHORT", "SELL"):
        return "SHORT"
    return "LONG"

def _levels_valid(direction: str, entry: float, stop: float, tp: float) -> bool:
    if direction == "LONG":
        return stop < entry < tp
    else:
        return tp < entry < stop

def _to_step(value: Decimal, step: Decimal) -> Decimal:
    """
    התאמה ל-stepSize (למטה) בצורה שמרנית.
    """
    if step <= 0:
        return value
    # floor(value/step) * step
    q = (value / step).to_integral_value(rounding=ROUND_FLOOR)
    return q * step

def _load_filters_cache() -> None:
    """
    טוען פעם אחת את exchangeInfo של Futures ובונה מילון פילטרים לסימבולים.
    נשמר בזיכרון עד ריסטארט (פשוט ויציב).
    """
    global _FILTERS_LOADED, _SYMBOL_FILTERS
    if _FILTERS_LOADED:
        return
    ei = futures_exchange_info_safe()
    if not isinstance(ei, dict) or "symbols" not in ei:
        logging.warning("[TRADE] לא הצלחתי לטעון futures_exchange_info – ממשיך ללא ולידציה מתקדמת.")
        _FILTERS_LOADED = True
        return

    for s in ei.get("symbols", []):
        sym = s.get("symbol")
        if not sym:
            continue
        lot_step = None
        min_qty  = None
        min_notional = None
        for f in s.get("filters", []):
            ftype = f.get("filterType")
            if ftype == "LOT_SIZE":
                lot_step = f.get("stepSize")  # string
                min_qty  = f.get("minQty")
            elif ftype in ("MIN_NOTIONAL", "NOTIONAL"):
                # בחלק מהחשבונות FUTURES השם הוא MIN_NOTIONAL, באחרים NOTIONAL
                # השדה בד"כ "notional"
                min_notional = f.get("notional") or f.get("minNotional")
        if lot_step or min_qty or min_notional:
            _SYMBOL_FILTERS[sym.upper()] = {
                "stepSize":     lot_step or "0",
                "minQty":       min_qty or "0",
                "minNotional":  min_notional or "0",
            }
    _FILTERS_LOADED = True
    logging.info("[TRADE] exchangeInfo נטען: %d סמלים עם פילטרים.", len(_SYMBOL_FILTERS))

def _get_symbol_filters(symbol: str) -> Dict[str, str]:
    """
    מחזיר dict עם stepSize/minQty/minNotional כמחרוזות. אם לא קיים – הכל "0".
    """
    _load_filters_cache()
    return _SYMBOL_FILTERS.get(symbol.upper(), {"stepSize": "0", "minQty": "0", "minNotional": "0"})

def _compute_qty_by_budget(
    symbol: str,
    live_price: float,
    leverage: int,
    budget_usd: float
) -> Tuple[Optional[Decimal], Optional[str]]:
    """
    מחשב כמות לפי תקציב ב-USD ולברג' (Futures):
    notional = budget_usd * leverage; qty = notional / price.
    לאחר מכן מתאים ל-stepSize ולודא מינימוםים לפי פילטרים (LOT_SIZE, MIN_NOTIONAL).
    אם הדרישות עולות על התקציב בצורה מהותית – מחזיר שגיאה.
    """
    try:
        filters = _get_symbol_filters(symbol)
        step = Decimal(filters.get("stepSize", "0") or "0")
        min_qty = Decimal(filters.get("minQty", "0") or "0")
        min_notional = Decimal(filters.get("minNotional", "0") or "0")

        price = Decimal(str(live_price))
        lev = max(MIN_LEVERAGE, min(int(leverage), MAX_LEVERAGE))
        planned_notional = Decimal(str(budget_usd)) * Decimal(str(lev))  # חשיפת פוזיציה

        # אם התקציב מאוד קטן/מחיר גבוה – היווצרות qty קטן מאוד
        raw_qty = (planned_notional / price) if price > 0 else Decimal("0")

        # התאמה ל-stepSize (למטה). אם אין stepSize ידוע – לא נוגעים.
        if step > 0:
            adj_qty = _to_step(raw_qty, step)
        else:
            adj_qty = raw_qty

        # ודא minQty
        if min_qty > 0 and adj_qty < min_qty:
            adj_qty = _to_step(min_qty, step) if step > 0 else min_qty

        # ודא MIN_NOTIONAL
        notional = adj_qty * price
        if min_notional > 0 and notional < min_notional:
            # נעלה את הכמות לשם עמידה במינימום נומינלי (עלול לחרוג מהתקציב/לברג')
            needed_qty = (min_notional / price)
            needed_qty = _to_step(needed_qty, step) if step > 0 else needed_qty
            notional = needed_qty * price
            # נעשה sanity: אם זה חורג ביותר מ-25% מהחשיפה המתוכננת — נעדיף לעצור
            if planned_notional > 0 and notional > planned_notional * Decimal("1.25"):
                return None, (f"required notional {notional:.4f} exceeds planned "
                              f"{planned_notional:.4f} by >25% (minNotional). Increase budget or leverage.")
            adj_qty = needed_qty

        # ודא שלא נחתכנו לאפס בגלל step
        if adj_qty <= 0:
            return None, "computed quantity ≤ 0 after step/min filters"

        return adj_qty, None
    except Exception as e:
        return None, f"qty compute error: {e}"

async def _get_live_price(symbol: str, max_age_sec: int) -> Optional[float]:
    """
    מנסה WS; אם לא טרי – נופל ל־REST מחיר.
    """
    price = await get_price_smart(symbol, max_age_sec=max_age_sec)
    return price

async def execute_trade_live(
    symbol: str,
    entry: float,
    stop: float,
    tp: float,
    direction: str,
    leverage: int = 20,
    budget_usd: float = 100,
    market_type: str = "futures",
    price_protect_pct: float | None = None,
) -> Dict[str, Any]:
    """
    מבצע טרייד חי עם הגנות:
    - אימות מחיר לייב + טריות (WS/REST fallback)
    - Price deviation guard
    - חישוב כמות לפי תקציב/לברג' + ולידציה מול פילטרים (LOT_SIZE, MIN_NOTIONAL)
    - jitter לפני POST, וריטריי עדין לטעויות זמניות (418/429/403/5xx)
    """
    try:
        symbol = str(symbol).upper()
        direction = _norm_direction(direction)
        entry = float(entry); stop = float(stop); tp = float(tp)
        lev = int(max(MIN_LEVERAGE, min(int(leverage), MAX_LEVERAGE)))
        pprotect = float(price_protect_pct or PRICE_PROTECT_PCT)

        # ולידציה לוגית של הרמות
        if not _levels_valid(direction, entry, stop, tp):
            return {"status": "error", "error": f"levels invalid for {direction} (entry={entry}, stop={stop}, tp={tp})"}

        # קבלת מחיר לייב עם fallback
        live_price = await _get_live_price(symbol, PRICE_MAX_AGE_SEC)
        if live_price is None:
            logging.error(f"[TRADE] ❌ live price unavailable for {symbol}")
            return {"status": "error", "error": "live price unavailable"}

        if not is_price_fresh(symbol, max_age_sec=PRICE_MAX_AGE_SEC):
            logging.info(f"[TRADE] live price for {symbol} came via REST or stale WS snapshot")

        # סטיית מחיר לעומת התוכנית
        deviation = abs((live_price - entry) / entry) * 100.0
        if deviation > pprotect:
            msg = f"price deviation {deviation:.4f}% > {pprotect}% (plan={entry}, live={live_price})"
            logging.warning(f"[TRADE] ⚠️ {symbol} {msg}")
            return {"status": "error", "error": msg, "entry": entry, "live_price": live_price}

        # ===== חישוב כמות לפי תקציב/לברג' + פילטרים =====
        qty_dec, qty_err = _compute_qty_by_budget(symbol, live_price, lev, budget_usd)
        if qty_err or qty_dec is None:
            logging.error(f"[TRADE] qty compute failed for {symbol}: {qty_err}")
            return {"status": "error", "error": qty_err or "quantity compute failed"}

        qty_float = float(qty_dec)

        # jitter קטן לפני POST ראשון (מפחית 403/429/WAF)
        await asyncio.sleep(random.uniform(0.12, 0.35))

        # ===== ריטריי עדין לביצוע =====
        last_err: Optional[str] = None
        for attempt in range(MAX_TRADE_RETRIES + 1):
            try:
                result = await binance_futures_trade(
                    symbol=symbol,
                    side=direction,
                    entry=live_price,   # נכנסים במחיר לייב שאומת
                    sl=stop,
                    tp=tp,
                    leverage=lev,
                    budget=float(budget_usd),
                    quantity=qty_float,       # <<< מוסרים כמות מדויקת לפי פילטרים
                    market_type=market_type,
                )
                logging.info(f"[TRADE] ✅ {direction} {symbol} price={live_price} qty={qty_float} dev={deviation:.4f}% -> {result}")
                return {
                    "status": "success",
                    "result": result,
                    "computed": {
                        "qty": float(qty_dec),
                        "live_price": live_price,
                        "planned_notional": float(budget_usd * lev),
                        "actual_notional": float(qty_dec * Decimal(str(live_price))),
                        "leverage": lev,
                    }
                }
            except Exception as e:
                err = str(e)
                last_err = err
                transient = any(code in err for code in (" 418", " 429", " 500", " 502", " 503", " 504", "403"))
                if attempt < MAX_TRADE_RETRIES and transient:
                    wait = BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 0.35)
                    logging.warning(f"[TRADE] retryable error (attempt {attempt+1}/{MAX_TRADE_RETRIES+1}) {symbol}: {err} -> sleep {wait:.2f}s")
                    await asyncio.sleep(wait)
                    continue
                logging.error(f"[TRADE] ❌ non-retryable or exhausted retries {symbol}: {err}")
                return {"status": "error", "error": err}

        return {"status": "error", "error": last_err or "unknown error"}  # לא אמור להגיע לכאן

    except Exception as e:
        logging.error(f"[TRADE] שגיאה בביצוע טרייד {symbol}: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}

















































