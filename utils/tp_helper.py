# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Dict, Any, List, Tuple, Optional
import os
import math

# ─── נפילות-רכות למטריקות (אם קיימות) ─────────────────────────────────────────
try:
    from utils.metrics_tracker import (
        inc_manage_once_placed, inc_manage_once_failed, observe_callback_rate,
        observe_be_distance_bps, observe_tp_ladders,  # type: ignore
    )
except Exception:
    def inc_manage_once_placed():  # type: ignore
        pass
    def inc_manage_once_failed():  # type: ignore
        pass
    def observe_callback_rate(_v: float):  # type: ignore
        pass
    def observe_be_distance_bps(_v: float):  # type: ignore
        pass
    def observe_tp_ladders(_n: int):  # type: ignore
        pass


# ─── עזרי עיגול לטיק/סטפ של בורסה ─────────────────────────────────────────────
def bn_round(value: float, step: float) -> float:
    if step <= 0:
        return value
    return math.floor(value / step) * step

def round_tick_dir(value: float, tick: float, direction: str) -> float:
    if tick <= 0:
        return value
    q = value / tick
    if direction.lower().startswith("up"):
        return math.ceil(q) * tick
    return math.floor(q) * tick


# ─── חישובי BE / Trail / Profit-Lock ───────────────────────────────────────────
def compute_be_price(entry: float, side_txt: str, offset_bps: int,
                     price_now: Optional[float], tick: float) -> float:
    """
    מחזיר מחיר SL בסגנון BE (offset_bps בבסיס bps), מכוון לצד.
    מוודא אי-דריסה של המחיר הנוכחי (לפי הטיק).
    """
    side_txt = side_txt.upper()
    bps = max(0, int(offset_bps))
    if side_txt == "BUY":
        be = float(entry) * (1.0 - (bps / 10_000.0))
        be = round_tick_dir(be, tick, "down")
        if price_now and be >= price_now:
            be = max(round_tick_dir(price_now - tick, tick, "down"), 0.0)
    else:
        be = float(entry) * (1.0 + (bps / 10_000.0))
        be = round_tick_dir(be, tick, "up")
        if price_now and be <= price_now:
            be = round_tick_dir(price_now + tick, tick, "up")
    # מטריקה: מרחק ב-bps
    if price_now and price_now > 0:
        dist_bps = abs((price_now - be) / price_now) * 10_000.0
        observe_be_distance_bps(dist_bps)
    return float(be)


def calc_adaptive_callback(atr: float, px: float, *,
                           atr_mult: Optional[float],
                           min_pct: float, max_pct: float) -> Optional[float]:
    """
    אם atr_mult None → אין טרייל. אחרת callback% = min/max על בסיס ATR.
    """
    if atr_mult is None:
        return None
    if px <= 0 or atr <= 0:
        # פוֹלבק קל: אם אין ATR/מחיר – החזר ערך שמרני
        cb = max(min_pct, min(max_pct, 0.5))
        observe_callback_rate(cb)
        return cb
    cb = (atr * float(atr_mult) / px) * 100.0
    cb = round(max(min_pct, min(max_pct, cb)), 1)
    observe_callback_rate(cb)
    return cb


def plan_profit_lock_steps(rr_steps_cfg: str) -> List[float]:
    """
    קלט ENV "PROFIT_LOCK_STEPS" למשל "1.0,1.5,2.0"
    החזרה: רשימת R-steps (float), אחרי סינון סביר.
    """
    raw = rr_steps_cfg.strip() if rr_steps_cfg else ""
    out: List[float] = []
    for chunk in raw.split(","):
        c = chunk.strip()
        if not c:
            continue
        try:
            v = float(c)
            if v > 0:
                out.append(v)
        except Exception:
            continue
    # שמירה על סדר, ללא כפילויות־סמוכות
    uniq: List[float] = []
    for v in out:
        if not uniq or abs(uniq[-1] - v) > 1e-9:
            uniq.append(v)
    return uniq


# ─── פעולות מול Binance (תלויות לקוח שהוזרק) ─────────────────────────────────
def prune_conflicting(client, symbol: str) -> None:
    """
    מסיר STOP/TRAIL ישנים כדי למנוע התנגשויות.
    """
    try:
        oo = client.futures_get_open_orders(symbol=symbol)
        for o in oo or []:
            t = str(o.get("type") or "")
            if t in ("STOP", "STOP_MARKET", "TRAILING_STOP_MARKET"):
                client.futures_cancel_order(symbol=symbol, orderId=o.get("orderId"))
    except Exception:
        # לא מפיל את הזרימה
        return


def place_be_stop(client, symbol: str, side_txt: str, be_price: float, coid: str,
                  working_type: str = "MARK_PRICE") -> Optional[Dict[str, Any]]:
    try:
        res = client.futures_create_order(
            symbol=symbol,
            side=("SELL" if side_txt.upper() == "BUY" else "BUY"),
            type="STOP_MARKET",
            stopPrice=be_price,
            closePosition=True,
            workingType=working_type,
            newClientOrderId=coid,
        )
        return res
    except Exception:
        return None


def place_tp_ladders(client, symbol: str, side_txt: str, base_price: float,
                     pcts: List[float], splits: List[float],
                     tick: float, step: float, qty_abs: float,
                     coid_builder) -> List[Dict[str, Any]]:
    """
    מחזיר רשימת TP שנפתחו בפועל: [{i, price, qty}]
    """
    placed = []
    try:
        for i, (pct, split) in enumerate(zip(pcts, splits), start=1):
            if pct <= 0 or split <= 0:
                continue
            if side_txt.upper() == "BUY":
                px = round_tick_dir(base_price * (1.0 + pct / 100.0), tick, "down")
                sd = "SELL"
            else:
                px = round_tick_dir(base_price * (1.0 - pct / 100.0), tick, "up")
                sd = "BUY"
            qty_i = bn_round(abs(qty_abs) * float(split), step)
            if qty_i <= 0:
                continue
            try:
                client.futures_create_order(
                    symbol=symbol,
                    side=sd,
                    type="LIMIT",
                    price=px,
                    quantity=qty_i,
                    timeInForce="GTC",
                    reduceOnly=True,
                    newClientOrderId=coid_builder(symbol, sd, role=f"TP{i}"),
                )
                placed.append({"i": i, "price": px, "qty": qty_i})
            except Exception:
                # ממשיכים לשאר הלהבים
                continue
    finally:
        observe_tp_ladders(len(placed))
    return placed


def place_trailing(client, symbol: str, side_txt: str, callback_rate: float,
                   coid: str, working_type: str = "MARK_PRICE") -> Optional[Dict[str, Any]]:
    try:
        res = client.futures_create_order(
            symbol=symbol,
            side=("SELL" if side_txt.upper() == "BUY" else "BUY"),
            type="TRAILING_STOP_MARKET",
            callbackRate=float(callback_rate),
            reduceOnly=True,
            workingType=working_type,
            newClientOrderId=coid,
        )
        return res
    except Exception:
        return None


# ─── Orchestrator ל-/manage-once ───────────────────────────────────────────────
def manage_once_place_all(*, client, symbol: str, side_txt: str,
                          entry_price: float, price_now: Optional[float],
                          qty_abs: float, tick: float, step: float,
                          offset_bps: int, pcts: List[float], splits: List[float],
                          atr: float, atr_mult: Optional[float],
                          working_type: str,
                          coid_builder,
                          dry_run: bool = False) -> Dict[str, Any]:
    """
    מפעיל:
      1) ניקוי STOP/TRAIL ישנים
      2) BE-Stop לפי offset_bps
      3) TP-ladders לפי pcts/splits
      4) Trailing אופציונלי לפי ATR*atr_mult
    """
    result: Dict[str, Any] = {
        "ok": True, "be_stop": None, "tp": [], "trail": None,
        "computed": {}, "dry_run": bool(dry_run),
    }

    # 0) אימות inputs בסיסי
    if len(pcts) != len(splits) or not (0.999 <= sum(splits) <= 1.001):
        return {"ok": False, "error": "pcts/splits mismatch or splits must sum to 1.0"}

    # 1) חישובי BE + Callback
    be_price = compute_be_price(entry_price, side_txt, int(offset_bps), price_now, tick)
    cb = calc_adaptive_callback(
        atr=float(atr),
        px=float(price_now or entry_price),
        atr_mult=atr_mult,
        min_pct=float(os.getenv("TRAIL_RT_MIN_CALLBACK", "0.1") or 0.1),
        max_pct=float(os.getenv("TRAIL_RT_MAX_CALLBACK", "5.0") or 5.0),
    )

    result["computed"] = {
        "be_price": be_price,
        "callback_rate": cb,
    }

    if dry_run:
        return result

    # 2) סנכרון הזמנות ישנות
    prune_conflicting(client, symbol)

    # 3) BE stop
    be_res = place_be_stop(
        client, symbol, side_txt, be_price,
        coid_builder(symbol, "SELL" if side_txt == "BUY" else "BUY", role="SL@BE"),
        working_type=working_type
    )
    result["be_stop"] = {"price": be_price, "ok": bool(be_res)}

    # 4) TP ladders
    placed_tp = place_tp_ladders(
        client, symbol, side_txt, float(price_now or entry_price),
        pcts, splits, tick, step, qty_abs, coid_builder
    )
    result["tp"] = placed_tp

    # 5) Trailing (אם יש cb)
    if cb is not None:
        trail_res = place_trailing(
            client, symbol, side_txt, cb,
            coid_builder(symbol, "SELL" if side_txt == "BUY" else "BUY", role="TRAIL"),
            working_type=working_type
        )
        result["trail"] = {"callbackRate": cb, "ok": bool(trail_res)}

    # מטריקות
    if result["be_stop"] and result["be_stop"]["ok"]:
        inc_manage_once_placed()
    else:
        inc_manage_once_failed()

    return result

