# utils/trade_client.py
from __future__ import annotations
import os, math, time
from typing import Any, Dict, Optional
from utils.binance_futures_exec import BinanceFuturesExec

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
    לקוח מסחר דק מול Binance Futures:
    - קריאת פוזיציה פעילה
    - הצבת SL/BE/TP כ־STOP_MARKET/TAKE_PROFIT_MARKET (reduceOnly)
    - פתיחה/סגירה MARKET
    - כיבוד tickSize/stepSize כדי למנוע Precision errors
    """
    def __init__(self):
        self.cli = BinanceFuturesExec()
        self._filters_cache: Dict[str, Dict[str, Any]] = {}
        self._filters_cache_ts: Dict[str, float] = {}

    def _filters(self, symbol: str) -> Dict[str, Any]:
        s = symbol.upper()
        now = time.time()
        if s in self._filters_cache and now - self._filters_cache_ts.get(s, 0) < EXCHANGE_INFO_TTL:
            return self._filters_cache[s]
        info = self.cli.get("/fapi/v1/exchangeInfo", {}, signed=False) or {}
        flt: Dict[str, Any] = {}
        for sym in info.get("symbols", []):
            if (sym.get("symbol") or "").upper() == s:
                for f in sym.get("filters", []):
                    if f.get("filterType") == "PRICE_FILTER":
                        flt["tickSize"] = float(f.get("tickSize") or 0)
                    elif f.get("filterType") == "LOT_SIZE":
                        flt["stepSize"] = float(f.get("stepSize") or 0)
                    elif f.get("filterType") == "MIN_NOTIONAL":
                        flt["minNotional"] = float(f.get("notional") or 0)
                break
        self._filters_cache[s] = flt
        self._filters_cache_ts[s] = now
        return flt

    def _round_price(self, symbol: str, price: float) -> float:
        if not ORDER_ROUND_TO_TICK: return float(price)
        flt = self._filters(symbol) if USE_EXCHANGE_FILTERS else {}
        tick = float(flt.get("tickSize") or 0) or _env_override_float(f"PRICE_DP_OVERRIDE__{symbol.upper()}") or 0.0
        p = float(price)
        if tick and tick > 0:
            return math.floor(p / tick) * tick
        dp = _env_override_float(f"PRICE_DP_OVERRIDE__{symbol.upper()}")
        if dp is not None:
            return float(f"{p:.{int(dp)}f}")
        return p

    def _round_qty(self, symbol: str, qty: float) -> float:
        flt = self._filters(symbol) if USE_EXCHANGE_FILTERS else {}
        step = float(flt.get("stepSize") or 0) or _env_override_float(f"QTY_STEP_OVERRIDE__{symbol.upper()}") or 0.0
        q = float(qty)
        if step and step > 0:
            return math.floor(q / step) * step
        return q

    # ===== API =====
    async def get_position(self, symbol: str) -> Dict[str, Any]:
        data = self.cli.get("/fapi/v2/positionRisk", {}, signed=True)
        s = symbol.upper()
        for row in data or []:
            if (row.get("symbol") or "").upper() == s:
                return row
        return {}

    async def cancel_all_reduce_only(self, symbol: str) -> None:
        # אם יש לך מחיקת הזמנות קיימת – חבר לכאן. כרגע no-op.
        return None

    async def place_stop_loss_or_be(self, symbol: str, side: str, stop_price: float, trigger: str = "mark") -> Dict[str, Any]:
        sp = self._round_price(symbol, float(stop_price))
        pos = await self.get_position(symbol)
        qty = self._round_qty(symbol, abs(float(pos.get("positionAmt") or 0.0)))
        if qty <= 0: raise RuntimeError("no position qty to protect")
        close_side = "SELL" if side.upper() == "BUY" else "BUY"
        return self.cli.order_tp_or_sl_market(symbol.upper(), close_side, sp, qty, kind="STOP_MARKET", position_side="BOTH", reduce_only=True)

    async def place_take_profit(self, symbol: str, side: str, tp_price: float, split: Optional[float], idx: int, trigger: str="mark") -> Dict[str, Any]:
        pp = self._round_price(symbol, float(tp_price))
        pos = await self.get_position(symbol)
        base_qty = abs(float(pos.get("positionAmt") or 0.0))
        use_qty = self._round_qty(symbol, base_qty * float(split if (split is not None) else 1.0))
        if use_qty <= 0: raise RuntimeError("tp split qty after rounding is 0")
        close_side = "SELL" if side.upper() == "BUY" else "BUY"
        return self.cli.order_tp_or_sl_market(symbol.upper(), close_side, pp, use_qty, kind="TAKE_PROFIT_MARKET", position_side="BOTH", reduce_only=True)

    async def close_position_market(self, symbol: str) -> None:
        pos = await self.get_position(symbol)
        amt = float(pos.get("positionAmt") or 0.0)
        s = symbol.upper()
        if amt > 0:
            q = self._round_qty(s, amt)
            if q > 0: self.cli.order_market(s, "SELL", q, position_side="BOTH", reduce_only=True)
        elif amt < 0:
            q = self._round_qty(s, abs(amt))
            if q > 0: self.cli.order_market(s, "BUY", q, position_side="BOTH", reduce_only=True)

    async def open_market(self, symbol: str, side: str, qty: float, leverage: int) -> Dict[str, Any]:
        self.cli.set_leverage(symbol.upper(), int(leverage))
        q = self._round_qty(symbol, float(qty))
        if q <= 0: raise RuntimeError("qty after rounding is 0")
        return self.cli.order_market(symbol.upper(), side.upper(), q, position_side="BOTH", reduce_only=False)
