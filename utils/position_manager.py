# utils/position_manager.py
# -*- coding: utf-8 -*-
from __future__ import annotations
"""
Position Manager (Lite): BE-stair בסיסי + ATR-based Trail
---------------------------------------------------------
מיועד לקריאה מתוך routes/manager.py::manage_once_lite()

חתימות תואמות:
    async def manage_once(symbol: Optional[str] = None,
                          offset_bps: Optional[int] = None,
                          pcts: Optional[list[float]] = None,
                          splits: Optional[list[float]] = None,
                          atr_mult: Optional[float] = None) -> dict

הקובץ בטוח לשימוש גם כשה־Binance SDK לא מותקן / מפתחות חסרים — יחזיר skipped=True.
"""

import os
import math
from typing import Any, Dict, List, Optional
from contextlib import suppress

# --- Metrics (אופציונלי; כרגע לא בשימוש ישיר) ---
with suppress(Exception):
    from utils.metrics_tracker import inc_scan_passed as _noop1  # noqa: F401
with suppress(Exception):
    from utils.metrics_tracker import inc_scan_blocked as _noop2  # noqa: F401

# --- COID helper (נקרא אם קיים, אחרת גרסה מקומית) ---
with suppress(Exception):
    from utils.order_ids import build_client_order_id as _build_id  # type: ignore

def _build_local_id(symbol: str, side: str, role: str = "GEN") -> str:
    import time, hashlib  # local to avoid global imports if unused
    pref = (os.getenv("ORDER_ID_PREFIX") or "ALG").strip() or "ALG"
    base = f"{pref}-{symbol.upper()}-{side.upper()}-{role.upper()}-{int(time.time()*1000)}"
    if len(base) <= 36:
        return base
    h = hashlib.md5(base.encode("utf-8")).hexdigest()[:6]
    return base[:36 - (len(h) + 1)] + "_" + h

def _coid(symbol: str, side: str, role: str) -> str:
    with suppress(Exception):
        return _build_id(symbol, side, role=role)  # type: ignore
    return _build_local_id(symbol, side, role)

# --- ENV knobs (ברירות מחדל עדינות) ---
BE_BASE_BPS      = int(os.getenv("BE_BASE_BPS", "5") or 5)
BE_ADX_FACTOR    = float(os.getenv("BE_ADX_FACTOR", "0.2") or 0.2)     # מוכן לשדרוג עתידי
TRAIL_MIN_PCT    = float(os.getenv("TRAIL_MIN_PCT", "0.08") or 0.08)   # אחוז
TRAIL_MAX_PCT    = float(os.getenv("TRAIL_MAX_PCT", "5.0") or 5.0)     # אחוז
BINANCE_WORKING  = os.getenv("BINANCE_WORKING_TYPE", "MARK_PRICE").upper()

# --- עוזרים מתמטיים (ticks/steps) ---
def _bn_round(value: float, step: float) -> float:
    if step <= 0:
        return value
    return math.floor(value / step) * step

def _round_tick_dir(value: float, step: float, direction: str) -> float:
    if step <= 0:
        return value
    q = value / step
    return (math.ceil(q) if direction.lower().startswith("up") else math.floor(q)) * step

def _get_filters(client, symbol: str) -> tuple[float, float]:
    tick = 0.1
    step = 0.001
    with suppress(Exception):
        ex = client.futures_exchange_info()
        for s in ex.get("symbols", []):
            if s.get("symbol") == symbol:
                for f in s.get("filters", []):
                    if f.get("filterType") == "PRICE_FILTER":
                        tick = float(f.get("tickSize", tick))
                    elif f.get("filterType") == "LOT_SIZE":
                        step = float(f.get("stepSize", step))
                break
    return tick, step

# --- ADX/ATR calculation (Lite) ---
def _wilder_smooth(values: List[float], period: int) -> List[float]:
    if not values or period <= 0 or len(values) < period:
        return []
    smoothed = [sum(values[:period]) / period]
    for v in values[period:]:
        smoothed.append((smoothed[-1] * (period - 1) + v) / period)
    return smoothed

def _ind_from_kl(klines: List[List[Any]], period: int = 14) -> Dict[str, float]:
    try:
        highs = [float(k[2]) for k in klines]
        lows  = [float(k[3]) for k in klines]
        closes= [float(k[4]) for k in klines]
        if len(closes) < period + 2:
            return {"price": closes[-1] if closes else 0.0, "atr": 0.0, "adx": 0.0}
        trs, plus_dm, minus_dm = [], [], []
        for i in range(1, len(closes)):
            h, l, ph, pl, pc = highs[i], lows[i], highs[i-1], lows[i-1], closes[i-1]
            trs.append(max(h - l, abs(h - pc), abs(l - pc)))
            up_move = h - ph
            down_move = pl - l
            plus_dm.append(up_move if (up_move > down_move and up_move > 0) else 0.0)
            minus_dm.append(down_move if (down_move > up_move and down_move > 0) else 0.0)
        atr_s = _wilder_smooth(trs, period)
        p_s   = _wilder_smooth(plus_dm, period)
        m_s   = _wilder_smooth(minus_dm, period)
        if not (atr_s and p_s and m_s):
            return {"price": closes[-1], "atr": 0.0, "adx": 0.0}
        plus_di = [(p/atr_s[i])*100 if atr_s[i] > 0 else 0.0 for i, p in enumerate(p_s)]
        minus_di= [(m/atr_s[i])*100 if atr_s[i] > 0 else 0.0 for i, m in enumerate(m_s)]
        dx = []
        for i in range(min(len(plus_di), len(minus_di))):
            s = plus_di[i] + minus_di[i]
            d = abs(plus_di[i] - minus_di[i])
            dx.append((d/s)*100 if s > 0 else 0.0)
        adx_s = _wilder_smooth(dx, period)
        adx = adx_s[-1] if adx_s else 0.0
        return {"price": closes[-1], "atr": float(atr_s[-1] if atr_s else 0.0), "adx": float(adx)}
    except Exception:
        return {"price": 0.0, "atr": 0.0, "adx": 0.0}

# --- Position helpers ---
def _align_position_mode(client) -> None:
    mode_override = (os.getenv("POSITION_MODE_OVERRIDE") or "").strip().lower()
    with suppress(Exception):
        if mode_override in ("hedge", "dual", "dual_side", "dual_side_position", "dualposition"):
            client.futures_change_position_mode(dualSidePosition="true")
        elif mode_override in ("oneway", "one_way", "single", "single_side", "oneside"):
            client.futures_change_position_mode(dualSidePosition="false")

async def manage_once(
    symbol: Optional[str] = None,
    offset_bps: Optional[int] = None,
    pcts: Optional[List[float]] = None,
    splits: Optional[List[float]] = None,
    atr_mult: Optional[float] = None,
) -> Dict[str, Any]:
    """
    BE@entry -> SL at BE-offset, TP ladder לפי pcts/splits, Trail לפי ATR*mult (אופציונלי).
    החזר בפורמט תואם ל-/manage-once הקיים אצלך (main.py).
    """
    # Binance client
    try:
        from binance.client import Client  # type: ignore
    except Exception as e:
        return {"ok": True, "delegated": False, "skipped": True, "reason": "binance_client_import_failed", "detail": str(e)}

    api_key = os.getenv("BINANCE_API_KEY", "").strip()
    api_sec = os.getenv("BINANCE_API_SECRET", "").strip()
    if not (api_key and api_sec):
        return {"ok": True, "delegated": False, "skipped": True, "reason": "binance_keys_missing"}

    if not symbol:
        return {"ok": False, "error": "missing symbol"}

    symbol = symbol.upper().strip()
    client = Client(api_key, api_sec)
    _align_position_mode(client)

    # Detect open position
    pos_amt = 0.0
    entry_price = None
    side_txt = None
    with suppress(Exception):
        positions = client.futures_position_information(symbol=symbol)
        for p in positions or []:
            amt = float(p.get("positionAmt") or 0.0)
            if abs(amt) > 0:
                pos_amt = amt
                entry_price = float(p.get("entryPrice") or 0.0)
                side_txt = "BUY" if amt > 0 else "SELL"
                break
    if not side_txt or not entry_price or abs(pos_amt) <= 0:
        return {"ok": True, "skipped": True, "reason": "no_open_position"}

    tick, step = _get_filters(client, symbol)

    # Last price (fallback entry)
    price_now = entry_price
    with suppress(Exception):
        t = client.futures_symbol_ticker(symbol=symbol)
        if t and "price" in t:
            price_now = float(t["price"]) or entry_price
    base_price = price_now or entry_price

    # Indicators from klines for ATR & ADX (for trail sizing)
    kl = []
    with suppress(Exception):
        kl = client.futures_klines(symbol=symbol, interval="1m", limit=60)
    ind = _ind_from_kl(kl or [], period=14)
    atr = float(ind.get("atr") or 0.0)
    adx = float(ind.get("adx") or 0.0)

    # Defaults
    _offset_bps = int(offset_bps if isinstance(offset_bps, int) else BE_BASE_BPS)
    _pcts  = list(pcts) if pcts else [4.0, 8.0, 16.0]
    _splits= list(splits) if splits else [0.30, 0.30, 0.40]
    _atr_mult = float(atr_mult) if (atr_mult is not None) else None

    # Validate ladders
    if len(_pcts) != len(_splits):
        return {"ok": False, "error": "pcts/splits length mismatch"}
    if not (0.999 <= sum(_splits) <= 1.001):
        return {"ok": False, "error": "splits must sum to 1.0"}
    if any(x <= 0 for x in _pcts) or any(x <= 0 for x in _splits):
        return {"ok": False, "error": "pcts/splits must be > 0"}

    # Place BE Stop (Reduce risk)
    if side_txt == "BUY":
        be_price = float(entry_price) * (1.0 - (_offset_bps / 10_000.0))
        be_price = _round_tick_dir(be_price, tick, "down")
        if base_price and be_price >= base_price:
            be_price = _bn_round(base_price - tick, tick)
    else:
        be_price = float(entry_price) * (1.0 + (_offset_bps / 10_000.0))
        be_price = _round_tick_dir(be_price, tick, "up")
        if base_price and be_price <= base_price:
            be_price = _round_tick_dir(base_price + tick, tick, "up")

    # Cancel existing SL/Trail to avoid conflicts
    with suppress(Exception):
        open_orders = client.futures_get_open_orders(symbol=symbol)
        for o in open_orders or []:
            t = str(o.get("type") or "")
            if t in ("STOP", "STOP_MARKET", "TRAILING_STOP_MARKET"):
                client.futures_cancel_order(symbol=symbol, orderId=o.get("orderId"))

    # Create BE Stop (STOP_MARKET closePosition)
    with suppress(Exception):
        sl_kwargs = dict(
            symbol=symbol,
            side=("SELL" if side_txt == "BUY" else "BUY"),
            type="STOP_MARKET",
            stopPrice=be_price,
            closePosition=True,
            workingType=BINANCE_WORKING,
            newClientOrderId=_coid(symbol, ("SELL" if side_txt == "BUY" else "BUY"), role="SL@BE"),
        )
        client.futures_create_order(**sl_kwargs)

    # TP ladder (ReduceOnly)
    qty_abs = abs(pos_amt)
    placed_tp: List[Dict[str, Any]] = []
    targets: List[float] = []
    for pct in _pcts:
        if side_txt == "BUY":
            px = base_price * (1.0 + pct / 100.0)
            px = _round_tick_dir(px, tick, "down")
        else:
            px = base_price * (1.0 - pct / 100.0)
            px = _round_tick_dir(px, tick, "up")
        targets.append(px)

    for i, (tp_price, split) in enumerate(zip(targets, _splits), start=1):
        qty_i = _bn_round(qty_abs * float(split), step)
        if qty_i <= 0:
            continue
        tp_kwargs = dict(
            symbol=symbol,
            side=("SELL" if side_txt == "BUY" else "BUY"),
            type="LIMIT",
            price=tp_price,
            quantity=qty_i,
            timeInForce="GTC",
            reduceOnly=True,
            newClientOrderId=_coid(symbol, ("SELL" if side_txt == "BUY" else "BUY"), role=f"TP{i}"),
        )
        with suppress(Exception):
            client.futures_create_order(**tp_kwargs)
            placed_tp.append({"i": i, "price": tp_price, "qty": qty_i})

    # ATR-based Trailing (optional)
    placed_trail = None
    if _atr_mult is not None:
        px = base_price or 0.0
        if px > 0:
            cb = (atr * float(_atr_mult) / px) * 100.0  # אחוז
            # Binance דורש 0.1–5.0; נכבד גם את ENV וגם את המינימום הרשמי
            binance_min_cb = 0.1
            cb = max(binance_min_cb, max(TRAIL_MIN_PCT, min(TRAIL_MAX_PCT, cb)))
            cb = round(cb, 1)
            trail_kwargs = dict(
                symbol=symbol,
                side=("SELL" if side_txt == "BUY" else "BUY"),
                type="TRAILING_STOP_MARKET",
                callbackRate=cb,
                reduceOnly=True,
                workingType=BINANCE_WORKING,
                newClientOrderId=_coid(symbol, ("SELL" if side_txt == "BUY" else "BUY"), role="TRAIL"),
            )
            with suppress(Exception):
                client.futures_create_order(**trail_kwargs)
                placed_trail = {"callbackRate": cb}

    return {
        "ok": True,
        "delegated": False,
        "symbol": symbol,
        "side": side_txt,
        "entry": float(entry_price),
        "be_stop_price": float(be_price),
        "tp": placed_tp,
        "trail": placed_trail,
        "profile": {
            "name": "LITE",
            "offset_bps": int(_offset_bps),
            "pcts": [float(x) for x in _pcts],
            "splits": [float(x) for x in _splits],
            "atr_mult": (_atr_mult if _atr_mult is not None else None),
        },
        "indicators": {
            "adx": round(adx, 2),
            "atr": float(atr),
            "price": float(base_price),
            "atr_pct": (float(atr) / float(base_price)) if base_price else 0.0,
        },
    }
