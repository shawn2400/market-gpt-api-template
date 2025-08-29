# utils/binance_trader.py
from __future__ import annotations
import os
import math
import logging
from typing import Dict, Any, Optional, Tuple

from utils.ws_fallback import get_price as cache_get_price, is_price_fresh
from utils.binance_client import (
    futures_mark_price,
    set_leverage,
    place_limit_order,
    futures_open_positions,
)

# נסה למשוך פילטרים אם קיימים ב-client שלך (לא חובה; יש Fallback)
try:
    from utils.binance_client import get_symbol_filters  # type: ignore
except Exception:
    get_symbol_filters = None  # type: ignore

logger = logging.getLogger("algogpt.binance.trader")

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _normalize_side(side: str) -> str:
    s = (side or "").strip().upper()
    if s in ("LONG", "BUY"):
        return "BUY"
    if s in ("SHORT", "SELL"):
        return "SELL"
    raise ValueError("side must be one of: LONG/SHORT or BUY/SELL")

def _calc_entry_price(side: str, mark: float, tick: float) -> float:
    """
    בוחר מחיר Limit שמבטיח Post-Only (GTX) ככל הניתן:
    BUY → מתחת ל-Mark; SELL → מעל ה-Mark. מכייל לפי tick.
    """
    if side == "BUY":
        raw = mark * 0.998  # ~0.2% מתחת ל-Mark
    else:
        raw = mark * 1.002  # ~0.2% מעל ה-Mark
    return _floor_to_tick(raw, tick)

def _floor_to_step(x: float, step: float) -> float:
    if step <= 0:
        return x
    return math.floor(x / step) * step

def _floor_to_tick(px: float, tick: float) -> float:
    if tick <= 0:
        return px
    return math.floor(px / tick) * tick

def _load_filters(symbol: str) -> Tuple[float, float]:
    """
    מנסה להביא stepSize/tickSize מפילטרים של הבורסה.
    אם לא זמין — לוקח ברירות מחדל מה-ENV.
    """
    default_step = float(os.getenv("DEFAULT_QTY_STEP", "0.001"))
    default_tick = float(os.getenv("DEFAULT_PRICE_TICK", "0.1"))
    if get_symbol_filters:
        try:
            f = get_symbol_filters(symbol) or {}
            step = float(f.get("stepSize") or default_step)
            tick = float(f.get("tickSize") or default_tick)
            return step, tick
        except Exception as e:
            logger.warning(f"[filters] failed for {symbol}: {e}")
    return default_step, default_tick

def _min_notional_ok(qty: float, price: float) -> bool:
    min_notional = float(os.getenv("MIN_NOTIONAL_USDT", "5"))
    return (qty * price) >= min_notional

def _fresh_or_rest_mark(symbol: str) -> Optional[float]:
    s = symbol.upper()
    px = cache_get_price(s)
    if px and is_price_fresh(s, max_age_sec=10):
        return float(px)
    return futures_mark_price(s)

def _hedge_position_side(side: str) -> Optional[str]:
    """
    אם BINANCE_HEDGE_MODE=true → החזר "LONG"/"SHORT" בהתאם ל-BUY/SELL.
    אחרת None (מצב Both).
    """
    hedge = os.getenv("BINANCE_HEDGE_MODE", "false").strip().lower() in ("1","true","yes")
    if not hedge:
        return None
    return "LONG" if side == "BUY" else "SHORT"

# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

async def binance_futures_trade(
    symbol: str,
    side: str,
    budget: float,
    leverage: int = 10,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    ביצוע טרייד ב-Binance Futures.
    - משתמש במחיר מה-WS Cache אם טרי; אחרת Fallback ל-REST.
    - כניסה ב-LIMIT Post-Only (GTX). אם נדחה ע"י "post only will take liquidity" → ניסיון תיקון/התרחקות אחד.
    - qty = budget / mark (ההתנהגות המקורית). המינוף משפיע על מרג'ין, לא על qty.
    - עיגול qty/price לפי פילטרים אם זמינים.
    """
    symbol = symbol.upper().strip()
    side   = _normalize_side(side)

    mark = _fresh_or_rest_mark(symbol)
    if not mark or mark <= 0:
        raise RuntimeError(f"Mark price unavailable for {symbol}")

    step, tick = _load_filters(symbol)
    qty_raw = float(budget) / float(mark)
    qty = max(_floor_to_step(qty_raw, step), step)  # לא פחות מ-step
    entry_price = _calc_entry_price(side, float(mark), tick)

    if not _min_notional_ok(qty, entry_price):
        raise RuntimeError(f"Order notional too small: qty*price={qty*entry_price:.3f} USDT (min {os.getenv('MIN_NOTIONAL_USDT','5')})")

    pos_side = _hedge_position_side(side)

    if dry_run:
        logger.info(f"[DRY RUN] {side} {symbol} budget={budget} qty≈{qty:.8f} lev={leverage} limit={entry_price:.8f}")
        return {
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "entry": entry_price,
            "leverage": leverage,
            "dry_run": True,
        }

    # נסה לעדכן מינוף (לא מפיל טרייד במקרה כישלון)
    try:
        set_leverage(symbol, leverage)
    except Exception as e:
        logger.error(f"[Leverage] failed for {symbol}: {e}")

    # שליחת LIMIT GTX
    try:
        order = place_limit_order(
            symbol=symbol,
            side=side,
            quantity=qty,
            price=entry_price,
            post_only=True,           # GTX
            reduce_only=False,
            position_side=pos_side,   # LONG/SHORT אם Hedge Mode, אחרת None
            time_in_force=None,       # None => GTX ב-client שלך
        )
    except Exception as e:
        # טיפול בשגיאת Post-Only (ייקח נזילות) — ננסה להתרחק עוד קצת פעם אחת
        msg = str(e).lower()
        if "post only" in msg or "take liquidity" in msg or "gtx" in msg:
            bump = 0.001  # הסטה נוספת של 0.1%
            if side == "BUY":
                entry_price = _floor_to_tick(entry_price * (1.0 - bump), tick)
            else:
                entry_price = _floor_to_tick(entry_price * (1.0 + bump), tick)
            try:
                order = place_limit_order(
                    symbol=symbol,
                    side=side,
                    quantity=qty,
                    price=entry_price,
                    post_only=True,
                    reduce_only=False,
                    position_side=pos_side,
                    time_in_force=None,
                )
            except Exception as e2:
                logger.error(f"[New LIMIT GTX][retry failed] {symbol} {side}: {e2}")
                raise
        else:
            logger.error(f"[New LIMIT GTX] failed {symbol} {side}: {e}")
            raise

    out = {
        "symbol": symbol,
        "side": side,
        "qty": qty,
        "entry": entry_price,
        "leverage": leverage,
        "order": {k: order.get(k) for k in ("orderId", "clientOrderId", "status", "price", "origQty", "type", "timeInForce")} if isinstance(order, dict) else {"info": str(order)},
    }
    logger.info(f"[New LIMIT GTX] {out}")
    return out


def force_close_position(symbol: str) -> Dict[str, Any]:
    """
    סגירת פוזיציה קיימת ב-Reduce-Only עם LIMIT+IOC (ללא Market).
    LONG → SELL במחיר מעט נמוך מה-mark; SHORT → BUY במחיר מעט גבוה.
    """
    symbol = symbol.upper().strip()
    positions = futures_open_positions() or []
    pos = next((p for p in positions if p.get("symbol") == symbol), None)
    if not pos:
        return {"symbol": symbol, "closedAmt": 0.0, "message": "no position for symbol"}

    amt = float(pos.get("positionAmt") or 0.0)
    if amt == 0.0:
        return {"symbol": symbol, "closedAmt": 0.0, "message": "no open amount"}

    mark = _fresh_or_rest_mark(symbol)
    if not mark or mark <= 0:
        raise RuntimeError(f"Mark price unavailable for {symbol}")

    step, tick = _load_filters(symbol)
    qty = abs(_floor_to_step(amt, step))
    if qty <= 0:
        return {"symbol": symbol, "closedAmt": 0.0, "message": "amount below step"}

    # מרווח בטיחות ל-IOC
    if amt > 0:
        side = "SELL"
        limit_px = _floor_to_tick(mark * 0.98, tick)   # 2% מתחת ל-Mark
    else:
        side = "BUY"
        limit_px = _floor_to_tick(mark * 1.02, tick)   # 2% מעל ה-Mark

    pos_side = _hedge_position_side(side)

    try:
        r = place_limit_order(
            symbol=symbol,
            side=side,
            quantity=qty,
            price=limit_px,
            post_only=False,          # לא Post-Only
            reduce_only=True,         # סגירה בלבד
            position_side=pos_side,   # LONG/SHORT אם Hedge Mode
            time_in_force="IOC",      # Immediate-Or-Cancel
        )
        logger.info(f"[Force Close IOC] {symbol} amt={amt} -> {side} limit={limit_px} resp={getattr(r,'orderId',None)}")
        return {
            "symbol": symbol,
            "closedAmt": amt,
            "side": side,
            "orderId": r.get("orderId") if isinstance(r, dict) else None,
            "status": r.get("status") if isinstance(r, dict) else None,
        }
    except Exception as e:
        logger.error(f"[Force Close IOC] failed for {symbol}: {e}")
        raise




































