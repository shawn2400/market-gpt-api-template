# utils/trade_client.py
from __future__ import annotations
import os, math, asyncio, time
from typing import Any, Dict, Optional

try:
    # אם יש לך כבר לקוח בינאנס – תרכז כאן
    from utils.binance_futures import BinanceFutures  # type: ignore
except Exception:
    BinanceFutures = None  # type: ignore

USE_EXCHANGE_FILTERS = os.getenv("USE_EXCHANGE_FILTERS","1").lower() in ("1","true","yes","on")
ORDER_ROUND_TO_TICK  = os.getenv("ORDER_ROUND_TO_TICK","1").lower() in ("1","true","yes","on")
EXCHANGE_INFO_TTL    = int(os.getenv("EXCHANGE_INFO_TTL_SEC","900"))

def _env_override_float(key: str) -> Optional[float]:
    v = os.getenv(key, "").strip()
    if not v: return None
    try: return float(v)
    except: return None

class TradeClient:
    """
    שכבה דקה שמבצעת:
    - קריאת פוזיציה פעילה
    - ביטול הזמנות reduceOnly
    - הצבת BE/SL/TP תקניים
    - פתיחה/סגירה מרקט
    - רינדור qty/price בהתאם לפילטרים של הבורסה (מונע Precision errors)
    """
    def __init__(self):
        if BinanceFutures is None:
            raise RuntimeError("BinanceFutures client missing; add utils/binance_futures.py or wire your client")
        self.cli = BinanceFutures()
        self._filters_cache: Dict[str, Dict[str, Any]] = {}
        self._filters_cache_ts: Dict[str, float] = {}

    async def _filters(self, symbol: str) -> Dict[str, Any]:
        s = symbol.upper()
        now = time.time()
        if s in self._filters_cache and now - self._filters_cache_ts.get(s, 0) < EXCHANGE_INFO_TTL:
            return self._filters_cache[s]
        f = await self.cli.get_symbol_filters(s)  # עליך לממש בלקוח שלך: מחזיר tickSize, stepSize, minQty, minNotional...
        self._filters_cache[s] = f or {}
        self._filters_cache_ts[s] = now
        return f or {}

    async def _round_price(self, symbol: str, price: float) -> float:
        if not ORDER_ROUND_TO_TICK: return price
        flt = await self._filters(symbol)
        tick = float(flt.get("tickSize") or 0) or _env_override_float(f"PRICE_DP_OVERRIDE__{symbol.upper()}") or 0.0
        if tick and tick > 0:
            return math.floor(price / tick) * tick
        # fallback דיפי אם אין tickSize
        dp = _env_override_float(f"PRICE_DP_OVERRIDE__{symbol.upper()}")
        if dp is not None:
            return float(f"{price:.{int(dp)}f}")
        return price

    async def _round_qty(self, symbol: str, qty: float) -> float:
        flt = await self._filters(symbol) if USE_EXCHANGE_FILTERS else {}
        step = float(flt.get("stepSize") or 0) or _env_override_float(f"QTY_STEP_OVERRIDE__{symbol.upper()}") or 0.0
        if step and step > 0:
            return math.floor(qty / step) * step
        # אם אין stepSize – לא נוגעים
        return qty

    # ===== API =====
    async def get_position(self, symbol: str) -> Dict[str, Any]:
        return await self.cli.get_position(symbol.upper())

    async def cancel_all_reduce_only(self, symbol: str) -> None:
        await self.cli.cancel_reduce_only(symbol.upper())

    async def place_stop_loss_or_be(self, symbol: str, side: str, stop_price: float, trigger: str = "mark") -> Dict[str, Any]:
        sp = await self._round_price(symbol, float(stop_price))
        return await self.cli.place_sl_or_be(symbol.upper(), side.upper(), sp, trigger=trigger)

    async def place_take_profit(self, symbol: str, side: str, tp_price: float, split: Optional[float], idx: int, trigger: str="mark") -> Dict[str, Any]:
        pp = await self._round_price(symbol, float(tp_price))
        return await self.cli.place_tp(symbol.upper(), side.upper(), pp, split=split, idx=idx, trigger=trigger)

    async def close_position_market(self, symbol: str) -> None:
        await self.cli.close_position_market(symbol.upper())

    async def open_market(self, symbol: str, side: str, qty: float, leverage: int) -> Dict[str, Any]:
        q = await self._round_qty(symbol, float(qty))
        if q <= 0: raise RuntimeError("qty after rounding is 0")
        return await self.cli.open_market(symbol.upper(), side.upper(), q, leverage=int(leverage))
