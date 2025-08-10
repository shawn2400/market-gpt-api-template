# utils/trade_executor.py
import asyncio
import logging
import random
from typing import Dict, Any, Optional

from utils import config
from utils.ws_fallback import get_price_smart, is_price_fresh
from utils.binance_trader import binance_futures_trade  # מניחים async ויציב

# קונפיג עם ברירות מחדל בטוחות
PRICE_PROTECT_PCT: float = float(getattr(config, "PRICE_PROTECT_PCT", 0.25))
PRICE_MAX_AGE_SEC: int = int(getattr(config, "PRICE_MAX_AGE_SEC", 10))
MAX_TRADE_RETRIES: int = int(getattr(config, "TRADE_MAX_RETRIES", 2))
BACKOFF_BASE: float = float(getattr(config, "TRADE_BACKOFF_BASE", 0.7))
MAX_LEVERAGE: int = int(getattr(config, "MAX_LEVERAGE", 35))  # שמרני: 5–35
MIN_LEVERAGE: int = 1

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

async def _get_live_price(symbol: str, max_age_sec: int) -> Optional[float]:
    """
    מנסה קודם WS; אם לא טרי/לא זמין – נופל ל־REST מחיר פוטו-אטומי.
    """
    # ניסיון מהיר: אם יש WS טרי – נעדיף אותו (get_price_smart כבר יטפל ב־fallback במקרה הצורך)
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
    - jitter לפני POST כדי לא להיתקע בקוצים של WAF/Rate Limit
    - ריטריי עדין לטעויות זמניות (418/429/403/5xx)
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

        # אם WS לא טרי ועדיין לא קיבלנו REST, תוודא לפחות שהמחיר לא עתיק
        if not is_price_fresh(symbol, max_age_sec=PRICE_MAX_AGE_SEC):
            logging.info(f"[TRADE] live price for {symbol} came via REST or stale WS snapshot")

        # שמירה מפני סטיית מחיר גבוהה מהתוכנית
        deviation = abs((live_price - entry) / entry) * 100.0
        if deviation > pprotect:
            msg = f"price deviation {deviation:.4f}% > {pprotect}% (plan={entry}, live={live_price})"
            logging.warning(f"[TRADE] ⚠️ {symbol} {msg}")
            return {"status": "error", "error": msg, "entry": entry, "live_price": live_price}

        # jitter קטן לפני POST ראשון (מפחית 403/429 בתזמונים צפופים)
        await asyncio.sleep(random.uniform(0.12, 0.35))

        # ריטריי עדין לשכבת ביצוע (לא אגרסיבי כדי לא להכפיל פוזיציות)
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
                    market_type=market_type,
                )
                logging.info(f"[TRADE] ✅ {direction} {symbol} price={live_price} dev={deviation:.4f}% -> {result}")
                return {"status": "success", "result": result}
            except Exception as e:
                err = str(e)
                last_err = err
                # שגיאות זמניות אופייניות: 418/429/5xx או CloudFront/WAF 403
                transient = any(code in err for code in (" 418", " 429", " 500", " 502", " 503", " 504", "403"))
                if attempt < MAX_TRADE_RETRIES and transient:
                    wait = BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 0.35)
                    logging.warning(f"[TRADE] retryable error (attempt {attempt+1}/{MAX_TRADE_RETRIES+1}) {symbol}: {err} -> sleep {wait:.2f}s")
                    await asyncio.sleep(wait)
                    continue
                logging.error(f"[TRADE] ❌ non-retryable or exhausted retries {symbol}: {err}")
                return {"status": "error", "error": err}

    except Exception as e:
        logging.error(f"[TRADE] שגיאה בביצוע טרייד {symbol}: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}
















































