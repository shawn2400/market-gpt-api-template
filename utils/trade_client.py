# utils/trade_client.py
from __future__ import annotations
import os, math, time, asyncio
from typing import Any, Dict, Optional, List, Tuple

try:
    # יש לך/תיישם את הלקוח בפנים (ראה "Contract" למטה)
    from utils.binance_futures import BinanceFutures  # type: ignore
except Exception:
    BinanceFutures = None  # type: ignore

# ===== ENV knobs =====
USE_EXCHANGE_FILTERS = os.getenv("USE_EXCHANGE_FILTERS","1").lower() in ("1","true","yes","on")
ORDER_ROUND_TO_TICK  = os.getenv("ORDER_ROUND_TO_TICK","1").lower() in ("1","true","yes","on")
EXCHANGE_INFO_TTL    = int(os.getenv("EXCHANGE_INFO_TTL_SEC","900"))
MIN_NOTIONAL_USDT    = float(os.getenv("MIN_NOTIONAL_USDT","5") or 5)
NATIVE_TPSL_ENABLE   = os.getenv("NATIVE_TPSL_ENABLE","1").lower() in ("1","true","yes","on")
ORDER_TRIGGER        = os.getenv("ORDER_TRIGGER","mark").upper()  # MARK / LAST / INDEX (בבינאנס: MARK_PRICE, LAST_PRICE)

# overrides אופציונליים: סימבול ספציפי או DEFAULT
def _env_override_float(key: str) -> Optional[float]:
    v = os.getenv(key, "").strip()
    if not v:
        return None
    try:
        return float(v)
    except:
        return None

def _env_override_f(symbol: str, key_prefix: str, default_key: str) -> Optional[float]:
    # למשל PRICE_DP_OVERRIDE__BTCUSDT או PRICE_DP_OVERRIDE__DEFAULT
    spec = _env_override_float(f"{key_prefix}__{symbol.upper()}")
    if spec is not None:
        return spec
    return _env_override_float(f"{key_prefix}__{default_key}")

class TradeClient:
    """
    שכבת שרות “דקה אבל חזקה” לבינאנס-פיוצ'רס:
    - רינדור price/qty ע"פ פילטרים (tickSize/stepSize/minQty/minNotional)
    - פתיחת מרקט + קביעת leverage/margin-mode (אם צריך)
    - הצבת/עדכון/ביטול TP/SL/BE (“native” reduceOnly)
    - קריאת פוזיציה/הזמנות פתוחות/מחיר מרק
    - מונע Precision errors ע"י עיגול נכון + בדיקות notional
    """

    def __init__(self):
        if BinanceFutures is None:
            raise RuntimeError("BinanceFutures client missing; provide utils/binance_futures.py")
        self.cli = BinanceFutures()
        self._filters_cache: Dict[str, Dict[str, Any]] = {}
        self._filters_cache_ts: Dict[str, float] = {}

    # ------------------------ Filters / rounding ------------------------
    async def _filters(self, symbol: str) -> Dict[str, Any]:
        s = symbol.upper()
        now = time.time()
        if s in self._filters_cache and now - self._filters_cache_ts.get(s, 0) < EXCHANGE_INFO_TTL:
            return self._filters_cache[s]
        f = await self.cli.get_symbol_filters(s)  # מחזיר: {"tickSize":..., "stepSize":..., "minQty":..., "minNotional":...}
        self._filters_cache[s] = f or {}
        self._filters_cache_ts[s] = now
        return f or {}

    async def _round_price(self, symbol: str, price: float) -> float:
        p = float(price)
        if not ORDER_ROUND_TO_TICK:
            return p
        flt = await self._filters(symbol) if USE_EXCHANGE_FILTERS else {}
        tick = float(flt.get("tickSize") or 0) or 0.0
        if tick <= 0:
            # fallback: דיפי עשרוני אופציונלי מסביבת הרצה
            dp = _env_override_f(symbol, "PRICE_DP_OVERRIDE", "DEFAULT")
            if dp is not None:
                return float(f"{p:.{int(dp)}f}")
            return p
        return math.floor(p / tick) * tick

    async def _round_qty(self, symbol: str, qty: float) -> float:
        q = float(qty)
        flt = await self._filters(symbol) if USE_EXCHANGE_FILTERS else {}
        step = float(flt.get("stepSize") or 0) or 0.0
        if step > 0:
            q = math.floor(q / step) * step
        else:
            # אופציונלי: override step
            step_ovr = _env_override_f(symbol, "QTY_STEP_OVERRIDE", "DEFAULT")
            if step_ovr and step_ovr > 0:
                q = math.floor(q / step_ovr) * step_ovr
        return q

    async def _min_notional(self, symbol: str) -> float:
        flt = await self._filters(symbol) if USE_EXCHANGE_FILTERS else {}
        mn = float(flt.get("minNotional") or 0) or MIN_NOTIONAL_USDT
        return max(mn, MIN_NOTIONAL_USDT)

    # ------------------------ Quick reads ------------------------
    async def get_position(self, symbol: str) -> Dict[str, Any]:
        """מחזיר פוזיציה (נורמלית; כולל qty>0 long qty<0 short, entryPrice, leverage, pnl וכו׳)."""
        return await self.cli.get_position(symbol.upper())

    async def get_open_orders(self, symbol: str) -> List[Dict[str, Any]]:
        return await self.cli.get_open_orders(symbol.upper())

    async def get_mark_price(self, symbol: str) -> float:
        return float(await self.cli.get_mark_price(symbol.upper()))

    # ------------------------ Order utils ------------------------
    async def ensure_notional(self, symbol: str, qty: float, price: Optional[float]=None) -> Tuple[float, float]:
        """
        מוודא שה־notional עומד במינימום: אם לא, מגדיל qty לעיגול step.
        מחזיר (qty_rounded, notional_usdt).
        """
        px = float(price) if price is not None else float(await self.get_mark_price(symbol))
        q = await self._round_qty(symbol, qty)
        notional = q * px
        mn = await self._min_notional(symbol)
        if notional < mn:
            # הגדלה מינימלית עד min notional
            need_q = mn / px
            q = await self._round_qty(symbol, need_q)
            notional = q * px
        if q <= 0:
            raise RuntimeError(f"qty after min-notional adjust is 0 (symbol={symbol})")
        return q, notional

    async def cancel_all_reduce_only(self, symbol: str) -> None:
        """מבטל כל ההזמנות reduceOnly (TP/SL וכו׳)."""
        await self.cli.cancel_reduce_only(symbol.upper())

    # ------------------------ Native TPSL / BE ------------------------
    async def place_stop_loss_or_be(
        self,
        symbol: str,
        side: str,
        stop_price: float,
        trigger: Optional[str] = None,
        be: bool = False
    ) -> Dict[str, Any]:
        """
        מציב SL/BE native (reduceOnly) לפי צד הפוזיציה (LONG/SHORT).
        side: LONG/SHORT (לא BUY/SELL) – כך ברור כיוון הפוזיציה.
        """
        trig = (trigger or ORDER_TRIGGER or "MARK").upper()
        sp = await self._round_price(symbol, float(stop_price))
        return await self.cli.place_sl_or_be(symbol.upper(), side.upper(), sp, trigger=trig, be=be)

    async def place_take_profit(
        self,
        symbol: str,
        side: str,
        tp_price: float,
        split: Optional[float],
        idx: int,
        trigger: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        מציב TP reduceOnly (לדרגה idx; split אופציונלי לצורך תיוג/כמות).
        side כאן הוא LONG/SHORT (כיוון פוזיציה) — הלקוח דואג ל-BUY/SELL בפועל.
        """
        trig = (trigger or ORDER_TRIGGER or "MARK").upper()
        pp = await self._round_price(symbol, float(tp_price))
        return await self.cli.place_tp(symbol.upper(), side.upper(), pp, split=split, idx=int(idx), trigger=trig)

    async def refresh_native_tpsl(
        self,
        symbol: str,
        side: str,
        sl_price: Optional[float],
        tp_levels: Optional[List[Tuple[float, Optional[float]]]] = None,
        be_price: Optional[float] = None,
        trigger: Optional[str] = None,
        keep_existing_tp: bool = False,
    ) -> Dict[str, Any]:
        """
        רענון TP/SL/BE “native”. אם keep_existing_tp=False → מבטל TP ישנים לפני הצבה.
        tp_levels: [(price, split), ...]
        """
        trig = (trigger or ORDER_TRIGGER or "MARK").upper()
        res: Dict[str, Any] = {"symbol": symbol.upper(), "side": side.upper(), "ops": []}

        if not NATIVE_TPSL_ENABLE:
            res["skipped"] = True
            res["reason"] = "native_tpsl_disabled"
            return res

        # בטל TP/SL קיימים (reduceOnly)
        if not keep_existing_tp:
            await self.cancel_all_reduce_only(symbol)
            res["ops"].append({"cancel_reduce_only": True})

        # SL / BE
        if sl_price is not None:
            sp = await self._round_price(symbol, float(sl_price))
            out = await self.cli.place_sl_or_be(symbol.upper(), side.upper(), sp, trigger=trig, be=False)
            res["ops"].append({"sl": out})
        if be_price is not None:
            bp = await self._round_price(symbol, float(be_price))
            out = await self.cli.place_sl_or_be(symbol.upper(), side.upper(), bp, trigger=trig, be=True)
            res["ops"].append({"be": out})

        # TP ladder
        if tp_levels:
            for i, (p, split) in enumerate(tp_levels, start=1):
                pp = await self._round_price(symbol, float(p))
                out = await self.cli.place_tp(symbol.upper(), side.upper(), pp, split=split, idx=i, trigger=trig)
                res["ops"].append({"tp": {"idx": i, "price": pp, "resp": out}})

        return res

    # ------------------------ Open / Close ------------------------
    async def open_market(self, symbol: str, side: str, qty: float, leverage: int) -> Dict[str, Any]:
        """
        פתיחת מרקט לפי BUY/SELL; דואג ל-qty לפחות מינימלי (minNotional) ולעיגול step.
        side: BUY / SELL (כיוון פעולה, לא כיוון פוזיציה).
        """
        px = await self.get_mark_price(symbol)
        q, notional = await self.ensure_notional(symbol, qty, price=px)
        return await self.cli.open_market(symbol.upper(), side.upper(), q, leverage=int(leverage))

    async def close_position_market(self, symbol: str) -> None:
        await self.cli.close_position_market(symbol.upper())

    # ------------------------ Helpers ------------------------
    @staticmethod
    def pos_side_from_qty(qty: float) -> str:
        """LONG אם qty>0, SHORT אם qty<0, NEUTRAL אם 0."""
        if qty > 0:  return "LONG"
        if qty < 0:  return "SHORT"
        return "NEUTRAL"

