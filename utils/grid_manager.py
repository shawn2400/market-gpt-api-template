# utils/grid_manager.py
from __future__ import annotations
from typing import Dict, Any, Tuple
from utils.precision_utils import apply_price_tick_side
from utils.binance_client import place_take_profit_market, place_stop_market

def _close_side(side: str) -> str:
    return "SELL" if side.upper() in ("BUY","LONG") else "BUY"

def compute_grid_levels(symbol: str, side: str, entry: float, atr: float) -> Dict[str, Any]:
    """
    TP1/TP2/TP3 מדורגים + SL ראשוני לפי ATR, עם יישור לטיקים.
    כמו שהגדרת: 1.0, 1.8, 2.6 ATR; SL = entry -/+ (1.5*ATR)
    """
    side_u = side.upper()
    sign = 1.0 if side_u in ("BUY","LONG") else -1.0
    tp1_raw = entry + sign * (1.0 * atr)
    tp2_raw = entry + sign * (1.8 * atr)
    tp3_raw = entry + sign * (2.6 * atr)
    sl_raw  = entry - sign * (1.5 * atr)

    close_side = _close_side(side_u)
    tp1, _ = apply_price_tick_side(tp1_raw, symbol, close_side)
    tp2, _ = apply_price_tick_side(tp2_raw, symbol, close_side)
    tp3, _ = apply_price_tick_side(tp3_raw, symbol, close_side)
    sl,  _ = apply_price_tick_side(sl_raw,  symbol, close_side)

    return {"tp1": float(tp1), "tp2": float(tp2), "tp3": float(tp3), "sl": float(sl)}

def ensure_grid_orders(symbol: str, side: str, qty: float, entry: float, atr: float) -> Dict[str, Any]:
    """
    יוצר 3 הזמנות TP Reduce-Only בכמויות מדורגות + SL ראשוני Reduce-Only.
    כמויות: 40% / 35% / 25%.
    """
    lv = compute_grid_levels(symbol, side, entry, atr)
    q1 = float(qty) * 0.40
    q2 = float(qty) * 0.35
    q3 = float(qty) * 0.25
    close_side = _close_side(side)

    out = {"ok": True, "placed": []}
    try:
        place_stop_market(symbol, close_side, float(lv["sl"]), float(qty), reduce_only=True)
        out["placed"].append({"type":"SL","price":lv["sl"],"qty":float(qty)})
    except Exception as e:
        out.setdefault("errors", []).append(f"SL_failed:{e}")
        out["ok"] = False

    for price, q, tag in ((lv["tp1"], q1, "TP1"), (lv["tp2"], q2, "TP2"), (lv["tp3"], q3, "TP3")):
        try:
            place_take_profit_market(symbol, close_side, float(price), float(q), reduce_only=True)
            out["placed"].append({"type":tag, "price":price, "qty":float(q)})
        except Exception as e:
            out.setdefault("errors", []).append(f"{tag}_failed:{e}")
            out["ok"] = False

    return out




