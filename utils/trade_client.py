# utils/trade_client.py
from __future__ import annotations
import os, math, time
from typing import Any, Dict, Optional, List, Tuple

try:
    from utils.binance_futures_exec import BinanceFuturesExec  # type: ignore
except Exception:
    BinanceFuturesExec = None  # type: ignore

USE_EXCHANGE_FILTERS = os.getenv("USE_EXCHANGE_FILTERS","1").lower() in ("1","true","yes","on")
ORDER_ROUND_TO_TICK  = os.getenv("ORDER_ROUND_TO_TICK","1").lower() in ("1","true","yes","on")
EXCHANGE_INFO_TTL    = int(os.getenv("EXCHANGE_INFO_TTL_SEC","900"))
MIN_NOTIONAL_USDT    = float(os.getenv("MIN_NOTIONAL_USDT","5") or 5)
ORDER_TRIGGER        = (os.getenv("ORDER_TRIGGER","mark") or "mark").upper()  # MARK/LAST/INDEX
POSITION_MODE_OVERRIDE = (os.getenv("POSITION_MODE_OVERRIDE","hedge") or "hedge").lower()

def _envf(key: str) -> Optional[float]:
    v = os.getenv(key, "").strip()
    if not v: return None
    try: return float(v)
    except: return None

def _ovr(symbol: str, prefix: str, default_key: str="DEFAULT") -> Optional[float]:
    spec = _envf(f"{prefix}__{symbol.upper()}")
    if spec is not None: return spec
    return _envf(f"{prefix}__{default_key}")

class TradeClient:
    """
    Binance Futures (USDT-M) trade helper:
    - tick/step rounding + minNotional guard (אוטומטי)
    - open/close market (כולל hedge LONG/SHORT)
    - native TP/SL/BE via *_MARKET reduceOnly
    - open orders & filters cache
    """
    def __init__(self):
        if BinanceFuturesExec is None:
            raise RuntimeError("utils.binance_futures_exec.BinanceFuturesExec missing")
        self.cli = BinanceFuturesExec()
        self._filters_cache: Dict[str, Dict[str, Any]] = {}
        self._filters_ts: Dict[str, float] = {}

        # הבטח מצב HEDGE אם ביקשת
        if POSITION_MODE_OVERRIDE in ("hedge","dual","dual_side","dualside"):
            try:
                self.cli.set_position_side_dual(True)
            except Exception:
                pass

    # -------- filters / rounding --------
    def _filters(self, symbol: str) -> Dict[str, Any]:
        s = symbol.upper()
        now = time.time()
        if s in self._filters_cache and now - self._filters_ts.get(s, 0) < EXCHANGE_INFO_TTL:
            return self._filters_cache[s]
        f = self.cli.get_exchange_filters(s) if USE_EXCHANGE_FILTERS else {}
        self._filters_cache[s] = f or {}
        self._filters_ts[s] = now
        return f or {}

    def _round_price(self, symbol: str, price: float) -> float:
        p = float(price)
        if not ORDER_ROUND_TO_TICK:
            return p
        flt = self._filters(symbol)
        tick = float(flt.get("tickSize") or 0) or 0.0
        if tick > 0:
            return math.floor(p / tick) * tick
        dp = _ovr(symbol, "PRICE_DP_OVERRIDE")
        if dp is not None:
            return float(f"{p:.{int(dp)}f}")
        return p

    def _round_qty(self, symbol: str, qty: float) -> float:
        q = float(qty)
        flt = self._filters(symbol) if USE_EXCHANGE_FILTERS else {}
        step = float(flt.get("stepSize") or 0) or 0.0
        if step > 0:
            q = math.floor(q / step) * step
        else:
            step_ovr = _ovr(symbol, "QTY_STEP_OVERRIDE")
            if step_ovr and step_ovr > 0:
                q = math.floor(q / step_ovr) * step_ovr
        return q

    def _min_notional(self, symbol: str) -> float:
        flt = self._filters(symbol) if USE_EXCHANGE_FILTERS else {}
        mn = float(flt.get("minNotional") or 0) or MIN_NOTIONAL_USDT
        return max(mn, MIN_NOTIONAL_USDT)

    # -------- reads --------
    def get_mark_price(self, symbol: str) -> float:
        return float(self.cli.get_mark_price(symbol.upper()))

    def get_open_orders(self, symbol: str) -> List[Dict[str, Any]]:
        return self.cli.get_open_orders(symbol.upper())

    def get_position(self, symbol: str) -> Dict[str, Any]:
        return self.cli.get_position(symbol.upper())

    # -------- internal calc --------
    def ensure_notional(self, symbol: str, qty: float, price: Optional[float]=None) -> Tuple[float, float]:
        px = float(price) if price is not None else self.get_mark_price(symbol)
        q = self._round_qty(symbol, qty)
        notional = q * px
        mn = self._min_notional(symbol)
        if notional < mn:
            need_q = mn / px
            q = self._round_qty(symbol, need_q)
            notional = q * px
        if q <= 0:
            raise RuntimeError(f"qty after min-notional adjust is 0 (symbol={symbol})")
        return q, notional

    # -------- cancels --------
    def cancel_reduce_only(self, symbol: str) -> None:
        """
        בטל רק reduceOnly; אם לא יודעים לזהות — בטל הכל.
        """
        try:
            orders = self.get_open_orders(symbol)
            ro_ids = [o.get("orderId") for o in orders if str(o.get("reduceOnly","false")).lower()=="true"]
            if ro_ids:
                for oid in ro_ids:
                    try:
                        self.cli.cancel_order(symbol.upper(), oid)
                    except Exception:
                        pass
                return
        except Exception:
            pass
        # fallback: cancel all
        try:
            self.cli.cancel_all_open_orders(symbol.upper())
        except Exception:
            pass

    # -------- TP/SL/BE (native reduceOnly using *_MARKET) --------
    def _close_side_from_pos(self, pos_side: str) -> str:
        # נרמל קלט: LONG/SHORT או BUY/SELL
        s = (pos_side or "").upper()
        if s in ("LONG","BUY"):
            return "SELL"
        if s in ("SHORT","SELL"):
            return "BUY"
        return "SELL"

    def _position_side(self, pos_side: str) -> str:
        s = (pos_side or "").upper()
        if s in ("LONG","BUY"):
            return "LONG"
        if s in ("SHORT","SELL"):
            return "SHORT"
        return "BOTH"

    def place_stop_loss_or_be(self, symbol: str, side: str, stop_price: float, trigger: str = "MARK", be: bool=False) -> Dict[str, Any]:
        """
        side: כיוון הפוזיציה (LONG/SHORT) או צד פעולה (BUY/SELL) – נתמוך בשניהם.
        """
        sp = self._round_price(symbol, float(stop_price))
        close_side = self._close_side_from_pos(side)
        pos_side = self._position_side(side)
        # כמות לסגירה — ננסה מגודל פוזיציה הנוכחי
        pos = self.get_position(symbol)
        amt = abs(float(pos.get("positionAmt") or 0.0))
        if amt <= 0:
            raise RuntimeError("no active position to protect")
        amt = self._round_qty(symbol, amt)
        kind = "TAKE_PROFIT_MARKET" if be else "STOP_MARKET"
        out = self.cli.order_tp_or_sl_market(
            symbol=symbol.upper(),
            side=close_side,
            stop_price=sp,
            quantity=amt,
            kind=kind,
            position_side=self._position_side(side),
            reduce_only=True,
            working_type=(trigger or ORDER_TRIGGER or "MARK").upper()+"_PRICE"
        )
        return {"ok": True, "resp": out, "stop": sp, "kind": kind}

    def place_take_profit(self, symbol: str, side: str, tp_price: float, split: Optional[float], idx: int, trigger: str="MARK") -> Dict[str, Any]:
        pp = self._round_price(symbol, float(tp_price))
        close_side = self._close_side_from_pos(side)
        pos_side = self._position_side(side)
        pos = self.get_position(symbol)
        amt = abs(float(pos.get("positionAmt") or 0.0))
        if amt <= 0:
            raise RuntimeError("no active position to TP")
        qty = amt
        if split is not None and 0 < float(split) < 1:
            qty = amt * float(split)
        qty = self._round_qty(symbol, qty)
        out = self.cli.order_tp_or_sl_market(
            symbol=symbol.upper(),
            side=close_side,
            stop_price=pp,
            quantity=qty,
            kind="TAKE_PROFIT_MARKET",
            position_side=pos_side,
            reduce_only=True,
            working_type=(trigger or ORDER_TRIGGER or "MARK").upper()+"_PRICE"
        )
        return {"ok": True, "resp": out, "tp": pp, "idx": int(idx), "qty": qty}

    # -------- open / close --------
    def open_market(self, symbol: str, side: str, qty: float, leverage: int) -> Dict[str, Any]:
        px = self.get_mark_price(symbol)
        q, _ = self.ensure_notional(symbol, qty, price=px)
        ps = "LONG" if side.upper()=="BUY" else "SHORT"
        try:
            self.cli.set_leverage(symbol.upper(), int(leverage))
        except Exception:
            pass
        out = self.cli.order_market(symbol.upper(), side.upper(), q, position_side=ps, reduce_only=False)
        return {"ok": True, "resp": out, "qty": q}

    def close_position_market(self, symbol: str) -> None:
        pos = self.get_position(symbol)
        amt = float(pos.get("positionAmt") or 0.0)
        if amt == 0:
            return
        side_close = "SELL" if amt > 0 else "BUY"
        ps = "LONG" if amt > 0 else "SHORT"
        qty = self._round_qty(symbol, abs(amt))
        self.cli.order_market(symbol.upper(), side_close, qty, position_side=ps, reduce_only=True)

