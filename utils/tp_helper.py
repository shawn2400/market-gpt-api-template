# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Dict, Any, List, Tuple, Optional
import os
import math

# ─── נפילות-רכות למטריקות (אם קיימות) ─────────────────────────────────────────
try:
    from utils.metrics_tracker import (
        inc_manage_once_placed, inc_manage_once_failed,
        observe_callback_rate, observe_be_distance_bps, observe_tp_ladders,
        inc_tp_merge, inc_tp_rearm, inc_tp_nudged,  # שלב 5
        observe_time_to_tp1,  # לשימוש עתידי (לא חובה כאן)
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
    def inc_tp_merge():  # type: ignore
        pass
    def inc_tp_rearm():  # type: ignore
        pass
    def inc_tp_nudged():  # type: ignore
        pass
    def observe_time_to_tp1(_sec: float):  # type: ignore
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


# ──────────────────────────────────────────────────────────────────────────────
# Merge / Rearm / Anti-stale  (שלב 5)
# ──────────────────────────────────────────────────────────────────────────────

def _side_txt_of_position_amt(amt: float) -> str:
    return "BUY" if float(amt) > 0 else "SELL"


def fetch_reduce_only_limits(client, symbol: str):
    """
    מחזיר רשימת הזמנות LIMIT עם reduceOnly=True (TPים פעילים).
    שדות עיקריים: price, side, orderId, origQty
    """
    out = []
    try:
        oo = client.futures_get_open_orders(symbol=symbol)
        for o in oo or []:
            if str(o.get("type")) == "LIMIT" and str(o.get("reduceOnly")).lower() == "true":
                try:
                    out.append({
                        "price": float(o.get("price")),
                        "side": str(o.get("side")),
                        "orderId": o.get("orderId"),
                        "origQty": float(o.get("origQty") or o.get("origqty") or 0.0),
                    })
                except Exception:
                    continue
    except Exception:
        pass
    out.sort(key=lambda x: x["price"])
    return out


def maybe_merge_close_tps(client, symbol: str, *, tick: float, tick_band: int) -> dict:
    """
    מאחד TPים קרובים: אם שני מחירים בטווח <= tick_band*tick,
    מבטל את השני, ומוסיף כמות נוספת למחיר הראשי (כהזמנה נוספת באותו מחיר).
    """
    ro = fetch_reduce_only_limits(client, symbol)
    if len(ro) < 2:
        return {"ok": True, "merged": 0}

    merged = 0
    band = max(1, int(tick_band)) * float(tick)

    i = 0
    while i + 1 < len(ro):
        a, b = ro[i], ro[i + 1]
        if abs(a["price"] - b["price"]) <= band and a["side"] == b["side"]:
            try:
                client.futures_cancel_order(symbol=symbol, orderId=b["orderId"])
            except Exception:
                i += 1
                continue
            try:
                client.futures_create_order(
                    symbol=symbol,
                    side=a["side"],
                    type="LIMIT",
                    price=a["price"],
                    quantity=b["origQty"],
                    timeInForce="GTC",
                    reduceOnly=True,
                )
                merged += 1
            except Exception:
                pass
            inc_tp_merge()
            ro = fetch_reduce_only_limits(client, symbol)
            i = 0
            continue
        i += 1

    return {"ok": True, "merged": merged}


def maybe_rearm_on_bounce(client, symbol: str, *, side_txt: str,
                          price_now: float, last_planned_tps: list,
                          tick: float, rearm_tick: int) -> dict:
    """
    Rearm פשוט: אם אין כרגע הזמנת LIMIT בטווח target±rearm_band,
    והמחיר קרוב ליעד "מוחמץ", נפתח שוב LIMIT קטן (10% מכמות משוערת).
    last_planned_tps: [{"price": <float>, "qty": <float>}, ...]
    """
    try:
        ro = fetch_reduce_only_limits(client, symbol)
        existing_prices = [r["price"] for r in ro]
        band = max(1, int(rearm_tick)) * float(tick)

        placed = 0
        for tp in last_planned_tps or []:
            tgt = float(tp.get("price", 0.0))
            qty_hint = max(0.0, float(tp.get("qty", 0.0)) * 0.10)  # 10% קטן
            if qty_hint <= 0 or tgt <= 0:
                continue
            close_enough = abs(price_now - tgt) <= band
            already_there = any(abs(p - tgt) <= band for p in existing_prices)
            if close_enough and (not already_there):
                try:
                    client.futures_create_order(
                        symbol=symbol,
                        side=("SELL" if side_txt.upper() == "BUY" else "BUY"),
                        type="LIMIT",
                        price=tgt,
                        quantity=qty_hint,
                        timeInForce="GTC",
                        reduceOnly=True,
                    )
                    inc_tp_rearm()
                    placed += 1
                except Exception:
                    continue
        return {"ok": True, "rearmed": placed}
    except Exception as e:
        return {"ok": False, "error": f"{e}"}


def anti_stale_nudge(client, symbol: str, *, side_txt: str,
                     tick: float, nudge_bps: float,
                     min_distance_ticks: int = 1) -> dict:
    """
    ניוד קל להחזרת TPים 'עייפים' לכיוון המחיר:
    - BUY: מורידים מחיר TP (קירוב) ב־bps, תוך שמירה על לפחות tick אחד מעל המחיר הנוכחי.
    - SELL: מעלים מחיר TP.
    """
    try:
        px = None
        try:
            t = client.futures_symbol_ticker(symbol=symbol)
            px = float(t["price"]) if t and "price" in t else None
        except Exception:
            px = None
        if not px:
            return {"ok": False, "error": "price_unavailable"}

        ro = fetch_reduce_only_limits(client, symbol)
        if not ro:
            return {"ok": True, "nudged": 0}
        moved = 0
        for o in ro:
            old = float(o["price"])
            if side_txt.upper() == "BUY":
                new = old * (1.0 - float(nudge_bps) / 10_000.0)
                min_ok = px + min_distance_ticks * float(tick)
                if new <= min_ok:
                    new = min_ok
            else:
                new = old * (1.0 + float(nudge_bps) / 10_000.0)
                min_ok = px - min_distance_ticks * float(tick)
                if new >= min_ok:
                    new = min_ok
            new_rounded = round_tick_dir(new, float(tick), "down" if side_txt.upper() == "BUY" else "up")
            if abs(new_rounded - old) >= float(tick):
                try:
                    client.futures_create_order(
                        symbol=symbol,
                        side=o["side"],
                        type="LIMIT",
                        price=new_rounded,
                        quantity=o["origQty"],
                        timeInForce="GTC",
                        reduceOnly=True,
                    )
                    client.futures_cancel_order(symbol=symbol, orderId=o["orderId"])
                    moved += 1
                except Exception:
                    continue
        if moved:
            inc_tp_nudged()
        return {"ok": True, "nudged": moved}
    except Exception as e:
        return {"ok": False, "error": f"{e}"}

