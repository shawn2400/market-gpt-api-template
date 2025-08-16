# routes/multi_scan.py
from __future__ import annotations

from fastapi import APIRouter, Query, Depends
from typing import Optional, List, Dict, Any, Tuple
import math
import pandas as pd

from utils.auth import require_bearer_token
from utils.multi_tf_scanner import multi_tf_scan_with_ai, fallback_scan_manual
from utils.btc_anchor import compute_btc_anchor
from utils.sl_tp_utils import calculate_sl_tp, get_sltp_params
from utils.precision_utils import apply_price_tick, apply_qty_step, get_precision_info
from utils.ws_fallback import snapshot_klines_df, get_price, is_price_fresh
from utils.binance_client import futures_exchange_info_safe
from utils import config

from ta.trend import ADXIndicator
from ta.volatility import AverageTrueRange

router = APIRouter(prefix="/scan", tags=["Multi-TF Scanner"], dependencies=[Depends(require_bearer_token)])

# ===================== Settings =====================
REF_TF = str(getattr(config, "SCAN_REF_TF", "15m"))
TP_TIER_MULTS: Tuple[float, ...] = tuple(getattr(config, "TP_TIER_MULTS", (0.8, 1.6, 2.5)))
PRICE_MAX_AGE_SEC = int(getattr(config, "PRICE_MAX_AGE_SEC", 10))
REFRESH_HINT_SEC = int(getattr(config, "SCAN_REFRESH_SEC", 60))

# meta
_STRATEGY_META = config.strategy_meta_snapshot()

# ===================== Risk helpers =====================
def _risk_metrics(symbol: str, interval: str = REF_TF, limit: int = 120) -> Dict[str, Optional[float]]:
    try:
        df: pd.DataFrame = snapshot_klines_df(symbol, interval=interval, limit=limit, market_type="futures")
        if df is None or df.empty:
            return {"atr": None, "atrp": None, "adx": None, "last": None}
        close = df["close"]; high = df["high"]; low = df["low"]
        atr14 = AverageTrueRange(high=high, low=low, close=close, window=14).average_true_range()
        adx14 = ADXIndicator(high=high, low=low, close=close, window=14).adx()
        atr = float(atr14.iloc[-1]); adx = float(adx14.iloc[-1]); last = float(close.iloc[-1])
        atrp = (atr / last * 100.0) if last > 0 else None
        return {"atr": atr, "atrp": atrp, "adx": adx, "last": last}
    except Exception:
        return {"atr": None, "atrp": None, "adx": None, "last": None}

def _tf_minutes(tf: str) -> int:
    s = (tf or "").strip().lower()
    if s.endswith("m"): return max(1, int(s[:-1]))
    if s.endswith("h"): return max(1, int(s[:-1])) * 60
    if s.endswith("d"): return max(1, int(s[:-1])) * 1440
    return 15

def _speed_pct_per_bar(symbol: str, interval: str = REF_TF, lookback: int = 120) -> float:
    try:
        df = snapshot_klines_df(symbol, interval=interval, limit=max(60, lookback), market_type="futures")
        if df is None or df.empty or len(df) < 30:
            base = {"5m": 0.12, "15m": 0.25, "1h": 0.60, "4h": 1.00}
            return float(base.get(interval, 0.30))
        close = df["close"].astype("float64")
        rets = (close.pct_change().abs() * 100.0).dropna()
        med = float(rets.rolling(20, min_periods=5).median().iloc[-1])
        if med <= 0 or math.isnan(med): med = float(rets.median())
        return max(0.05, min(5.0, med))
    except Exception:
        return 0.30

def _eta_minutes(distance_pct: float, speed_pct_per_bar: float, tf_minutes: int, adx: Optional[float], atrp: Optional[float]) -> Dict[str, int]:
    if speed_pct_per_bar <= 0: speed_pct_per_bar = 0.30
    bars = max(0.5, float(distance_pct) / float(speed_pct_per_bar))
    if adx is not None:
        a = float(adx)
        if a >= 35: bars *= 0.75
        elif a >= 25: bars *= 0.85
        elif a < 15:  bars *= 1.25
    if atrp is not None:
        v = float(atrp)
        if v >= 1.5: bars *= 0.90
        elif v <= 0.5: bars *= 1.10
    minutes = int(round(bars * tf_minutes))
    lo = max(1, int(round(minutes * 0.7)))
    hi = max(lo + 1, int(round(minutes * 1.3)))
    return {"eta_min": minutes, "eta_window_min": lo, "eta_window_max": hi}

# ===================== Leverage / Probabilities =====================
def _auto_leverage(atrp: Optional[float], adx: Optional[float], btc_strength: Optional[float], quality: Optional[float]) -> int:
    q = float(quality or 7.0)
    base = 10.0 + max(0.0, min(14.0, (q - 6.0) * 3.5))  # 6→10, 10→24
    boost = 0.0
    if adx is not None:          boost += max(0.0, min(6.0, (float(adx) - 20.0) * 0.3))
    if btc_strength is not None: boost += max(0.0, min(5.0, (float(btc_strength) - 55.0) * 0.15))
    penalty = 0.0
    if atrp is not None:
        if atrp >= 2.0: penalty = 10.0
        elif atrp >= 1.2: penalty = 6.0
        elif atrp >= 0.8: penalty = 3.0
    lev = base + boost - penalty
    return int(max(5.0, min(35.0, round(lev))))

def _win_probability(*, quality: float, confidence: Optional[float], adx: Optional[float], atrp: Optional[float],
                     btc_strength: Optional[float], dir_aligned_with_btc: Optional[bool]) -> int:
    q = max(0.0, min(10.0, float(quality or 0.0)))
    base = 50.0 + (q - 6.0) * 6.5
    if confidence is not None: base += (float(confidence) - 50.0) * 0.15
    if adx is not None:        base += min(12.0, max(0.0, float(adx) - 20.0) * 0.5)
    if atrp is not None:
        v = float(atrp)
        if v >= 2.0: base -= 12.0
        elif v >= 1.2: base -= 7.0
        elif v >= 0.8: base -= 3.0
    if btc_strength is not None and dir_aligned_with_btc is not None:
        s = float(btc_strength); adj = min(10.0, max(0.0, (s - 55.0) * 0.2))
        base += adj if dir_aligned_with_btc else -adj
    return int(round(max(5.0, min(97.0, base))))

def _tier_probability(base_win: int, tier_index: int, adx: Optional[float], atrp: Optional[float], aligned: Optional[bool]) -> int:
    adj = 0
    if tier_index == 0:
        adj += 4
        if adx is not None and adx >= 30: adj += 2
    elif tier_index == 2:
        adj -= 8
        if adx is not None and adx < 18: adj -= 4
    if atrp is not None:
        v = float(atrp)
        if v >= 1.5: adj -= 4
        elif v <= 0.5: adj += 2
    if aligned is False: adj -= 3
    return int(max(3, min(99, base_win + adj)))

def _entry_fill_probability(distance_pct: float, adx: Optional[float], atrp: Optional[float], aligned: Optional[bool]) -> int:
    d = max(0.0, float(distance_pct))
    if d <= 0.10: base = 88.0
    elif d <= 0.30: base = 78.0 - (d - 0.10) * (20.0 / 0.20)
    elif d <= 0.60: base = 58.0 - (d - 0.30) * (23.0 / 0.30)
    elif d <= 1.00: base = 35.0 - (d - 0.60) * (10.0 / 0.40)
    elif d <= 2.00: base = 25.0 - (d - 1.00) * (10.0 / 1.00)
    else: base = 12.0
    if adx is not None:
        a = float(adx)
        if a >= 35: base += 8.0
        elif a >= 25: base += 4.0
        elif a < 15:  base -= 4.0
    if atrp is not None:
        v = float(atrp)
        if v >= 1.8: base -= 5.0
        elif v <= 0.5: base -= 3.0
    if aligned is False: base -= 3.0
    return int(round(max(3.0, min(98.0, base))))

# ===================== Exchange info helpers =====================
_ei_cache: Optional[Dict[str, Any]] = None
def _exchange_info() -> Dict[str, Any]:
    global _ei_cache
    if _ei_cache is None:
        _ei_cache = futures_exchange_info_safe() or {}
    return _ei_cache

def _symbol_filters(symbol: str) -> Dict[str, Any]:
    su = str(symbol).upper()
    for s in _exchange_info().get("symbols", []) or []:
        if s.get("symbol") == su:
            out = {"tickSize": None, "stepSize": None, "minQty": None, "minNotional": None}
            for f in s.get("filters", []) or []:
                t = f.get("filterType")
                if t == "PRICE_FILTER": out["tickSize"] = f.get("tickSize")
                elif t == "LOT_SIZE":
                    out["stepSize"] = f.get("stepSize")
                    out["minQty"]   = f.get("minQty") or f.get("minQtyStep")
                elif t in ("MIN_NOTIONAL", "NOTIONAL"):
                    mn = f.get("notional") or f.get("minNotional") or f.get("minNotionalValue")
                    out["minNotional"] = mn
            return out
    return {"tickSize": None, "stepSize": None, "minQty": None, "minNotional": None}

def _qty_from_budget(symbol: str, price: float, budget_usd: float, leverage: float) -> Dict[str, Any]:
    flt = _symbol_filters(symbol)
    step = float(flt["stepSize"] or 0.0)
    min_qty = float(flt["minQty"] or 0.0)
    min_notional = float(flt["minNotional"] or 0.0)

    theo_qty = (float(budget_usd) * float(leverage)) / float(price) if float(price) > 0 else 0.0
    if step > 0:
        q_adj, q_str = apply_qty_step(theo_qty, symbol)
    else:
        q_adj = theo_qty
        q_str = f"{q_adj:.6f}"

    if min_qty and q_adj < min_qty:
        q_adj = min_qty
        q_adj, q_str = apply_qty_step(q_adj, symbol)

    notional = q_adj * float(price)
    ok = True
    reason = None
    if min_notional and notional < min_notional:
        ok = False
        reason = f"notional<{min_notional}"
    if q_adj <= 0:
        ok = False
        reason = reason or "qty<=0"

    return {
        "ok": ok,
        "reason": reason,
        "qty": float(q_adj),
        "qty_str": q_str,
        "notional": float(notional),
        "min_notional": float(min_notional) if min_notional else None,
        "min_qty": float(min_qty) if min_qty else None,
        "step_size": step if step else None,
    }

# ===================== TP tiers =====================
def _tp_tiers(symbol: str, entry: float, direction: str, atr: Optional[float]) -> List[Dict[str, Any]]:
    params = get_sltp_params()
    floor = float(params.get("tp_pct_floor", 0.006))
    atr_mult = float(params.get("atr_tp_mult", 2.5))
    base_off = max((float(atr or 0.0) * atr_mult) if (atr and atr > 0) else 0.0, float(entry) * floor)
    tiers: List[Dict[str, Any]] = []
    for i, m in enumerate(TP_TIER_MULTS, start=1):
        off = base_off * float(m)
        raw = entry + off if direction == "LONG" else entry - off
        adj, s = apply_price_tick(raw, symbol)
        dist_pct = abs((adj - entry) / entry) * 100.0
        tiers.append({
            "level": f"TP{i}",
            "price": float(adj),
            "price_str": s,
            "distance_pct": round(dist_pct, 6),
            "mult_of_base": float(m),
        })
    return tiers

# ===================== Plan builder =====================
async def _build_ready_plan(item: Dict[str, Any], market_type: str, budget_usd: float, btc_strength: Optional[float], btc_dir: Optional[str]) -> Dict[str, Any]:
    sym = str(item.get("symbol", "")).upper()
    direction = str(item.get("direction", "LONG")).upper()
    quality = float(item.get("quality_score", 0.0) or 0.0)
    confidence = float(item.get("confidence", 50.0) or 50.0)
    dir_aligned_with_btc = (direction == str(btc_dir or "").upper()) if btc_dir else None

    entry = item.get("entry"); atr = item.get("atr"); adx = item.get("adx")

    risk = _risk_metrics(sym, interval=REF_TF, limit=120)
    if atr is None: atr = risk.get("atr")
    if adx is None: adx = risk.get("adx")
    atrp = risk.get("atrp")

    leverage = _auto_leverage(atrp, adx, btc_strength, quality) if market_type == "futures" else None
    lev_eff = float(leverage or 1)

    if entry is None:
        lp = await get_price(sym)
        if lp is not None and is_price_fresh(sym, max_age_sec=PRICE_MAX_AGE_SEC):
            entry = float(lp)
        else:
            entry = risk.get("last")

    if entry is None or float(entry) <= 0:
        return {**item, "ready_plan": {"plan_ok": False, "plan_reason": "missing_entry"}}

    sl_raw, tp_raw = calculate_sl_tp(entry_price=float(entry), direction=direction, atr=float(atr) if atr is not None else None)
    entry_adj, entry_str = apply_price_tick(float(entry), sym)
    sl_adj,    sl_str    = apply_price_tick(float(sl_raw), sym)
    tp_adj,    tp_str    = apply_price_tick(float(tp_raw), sym)

    qty_res = _qty_from_budget(sym, price=entry_adj, budget_usd=float(budget_usd), leverage=lev_eff if market_type == "futures" else 1.0)

    live_price = await get_price(sym)
    dev_pct = None
    if live_price is not None and entry_adj > 0:
        dev_pct = abs((float(live_price) - entry_adj) / entry_adj) * 100.0
    dist_to_entry_pct = float(dev_pct or 0.0)
    spd = _speed_pct_per_bar(sym, interval=REF_TF, lookback=120)
    tfm = _tf_minutes(REF_TF)
    entry_eta = _eta_minutes(distance_pct=dist_to_entry_pct, speed_pct_per_bar=spd, tf_minutes=tfm, adx=adx, atrp=atrp)
    entry_prob = _entry_fill_probability(distance_pct=dist_to_entry_pct, adx=adx, atrp=atrp, aligned=dir_aligned_with_btc)

    tiers = _tp_tiers(sym, entry_adj, direction, atr)
    base_win = _win_probability(quality=quality, confidence=confidence, adx=adx, atrp=atrp, btc_strength=btc_strength, dir_aligned_with_btc=dir_aligned_with_btc)
    for idx, t in enumerate(tiers):
        t_eta = _eta_minutes(distance_pct=t["distance_pct"], speed_pct_per_bar=spd, tf_minutes=tfm, adx=adx, atrp=atrp)
        t_prob = _tier_probability(base_win, idx, adx, atrp, dir_aligned_with_btc)
        t.update({"eta_min": t_eta["eta_min"], "eta_window_min": t_eta["eta_window_min"], "eta_window_max": t_eta["eta_window_max"], "prob_pct": t_prob})

    position_value_usd = float(budget_usd) * lev_eff
    initial_margin_usd = float(budget_usd)

    # --- params snapshot for traceability ---
    params_snapshot = {
        "strategy_version": _STRATEGY_META["version"],
        "tp_tier_mults": TP_TIER_MULTS,
        "ref_tf": REF_TF,
        "sltp_params": get_sltp_params(),
        "price_max_age_sec": PRICE_MAX_AGE_SEC,
    }

    plan: Dict[str, Any] = {
        "strategy_version": _STRATEGY_META["version"],
        "params_snapshot": params_snapshot,
        "symbol": sym,
        "side": direction,
        "market_type": market_type,
        "entry": entry_adj, "entry_str": entry_str,
        "sl": sl_adj, "sl_str": sl_str,
        "tp": tp_adj, "tp_str": tp_str,
        "risk": {
            "atr": float(atr) if atr is not None else None,
            "adx": float(adx) if adx is not None else None,
            "atrp": float(atrp) if atrp is not None else None,
            "btc_anchor_strength": float(btc_strength) if btc_strength is not None else None,
            "btc_anchor_direction": btc_dir,
        },
        "quality_score": float(quality),
        "confidence": int(round(confidence)),
        "leverage": int(leverage) if leverage is not None else None,
        "position_value_usd": round(position_value_usd, 6),
        "initial_margin_usd": round(initial_margin_usd, 6),
        "live_price": float(live_price) if live_price is not None else None,
        "deviation_pct": round(dev_pct, 6) if dev_pct is not None else None,
        "entry_eta_min": int(entry_eta["eta_min"]),
        "entry_eta_window_min": int(entry_eta["eta_window_min"]),
        "entry_eta_window_max": int(entry_eta["eta_window_max"]),
        "entry_fill_prob_pct": int(entry_prob),
        "refresh_hint_sec": int(REFRESH_HINT_SEC),
    }

    qty_ok = qty_res.get("ok", False)
    if qty_ok:
        qty = float(qty_res["qty"]); qty_str = qty_res["qty_str"]; notional = float(qty_res["notional"])
        plan["quantity"] = qty; plan["quantity_str"] = qty_str
        plan["notional"] = notional
        plan["min_notional"] = float(qty_res["min_notional"]) if qty_res.get("min_notional") is not None else None
        out_tiers = []
        for t in tiers:
            tp_price = float(t["price"])
            pnl_per_unit = (tp_price - entry_adj) if direction == "LONG" else (entry_adj - tp_price)
            pnl_usd = max(0.0, pnl_per_unit * qty)
            t2 = dict(t)
            t2["pnl_usd"] = round(float(pnl_usd), 6)
            out_tiers.append(t2)
        plan["tp_tiers"] = out_tiers
        plan["plan_ok"] = True

        order_tmpl = {
            "strategy_version": _STRATEGY_META["version"],
            "params_snapshot": params_snapshot,
            "symbol": sym,
            "side": direction,          # Futures: LONG=BUY, SHORT=SELL
            "type": "LIMIT",
            "price": entry_str,
            "quantity": qty_str,
            "stop_loss": sl_str,
            "take_profit": tp_str,
            "leverage": int(leverage) if leverage is not None else None,
            "position_value_usd": round(position_value_usd, 6),
            "win_prob_pct": int(base_win),
            "entry_eta_min": int(entry_eta["eta_min"]),
            "entry_fill_prob_pct": int(entry_prob),
            "tp": [
                {
                    "level": t["level"],
                    "price": t["price_str"],
                    "prob_pct": t["prob_pct"],
                    "eta_min": t["eta_min"],
                    "pnl_usd": t["pnl_usd"],
                } for t in out_tiers
            ],
        }
        plan["order_template"] = order_tmpl
    else:
        plan.update({
            "plan_ok": False,
            "plan_reason": qty_res.get("reason", "qty_failed"),
            "quantity": 0.0,
            "quantity_str": "0",
            "notional": qty_res.get("notional"),
            "min_notional": qty_res.get("min_notional"),
            "tp_tiers": tiers,
            "order_template": {
                "strategy_version": _STRATEGY_META["version"],
                "params_snapshot": params_snapshot,
                "symbol": sym,
                "side": direction,
                "type": "LIMIT",
                "price": entry_str,
                "quantity": "0",
                "stop_loss": sl_str,
                "take_profit": tp_str,
                "leverage": int(leverage) if leverage is not None else None,
                "position_value_usd": round(position_value_usd, 6),
                "win_prob_pct": int(base_win),
                "entry_eta_min": int(entry_eta["eta_min"]),
                "entry_fill_prob_pct": int(entry_prob),
                "tp": [
                    {
                        "level": t["level"],
                        "price": t["price_str"],
                        "prob_pct": _tier_probability(base_win, idx, adx, atrp, dir_aligned_with_btc),
                        "eta_min": _eta_minutes(t["distance_pct"], spd, tfm, adx, atrp)["eta_min"],
                        "pnl_usd": 0.0,
                    } for idx, t in enumerate(tiers)
                ],
            },
        })

    plan["win_prob_pct"] = int(base_win)
    return {**item, "ready_plan": plan}

# ===================== API =====================
@router.get("/multi")
async def scan_multi(
    interval: Optional[str] = Query("5m,15m,1h", description="רשימת טיימפריימים מופרדים בפסיקים"),
    min_quality: int = Query(6, ge=1, le=10, description="ציון איכות מינימלי (0–10)"),
    top: int = Query(10, ge=1, description="מספר הטריידים המובילים"),
    market_type: Optional[str] = Query("futures", description="סוג שוק: futures או spot"),
    trending_only: Optional[bool] = Query(False, description="האם לסנן רק מטבעות טרנדיים"),
    trending_source: Optional[str] = Query("coingecko", description="מקור למטבעות טרנדיים"),
    budget_usd: Optional[float] = Query(None, description="תקציב לטרייד (USD). מינימום 50$. אם לא יועבר: config.MAX_TRADE_BUDGET"),
    include_results: Optional[bool] = Query(True, description="להחזיר גם נתוני results הגולמיים"),
):
    try:
        timeframes = tuple(s for s in (interval or "").split(",") if s)
        results = await multi_tf_scan_with_ai(
            timeframes=timeframes,
            markets=(market_type,),
            min_quality=min_quality,
            top=top,
            trending_only=trending_only,
            trending_source=trending_source
        )

        if not results:
            fb = await fallback_scan_manual("BTCUSDT")
            return {"warning": "לא נמצאו טריידים איכותיים, הופעל fallback ידני", "results": fb, "ready": []}

        anch = await compute_btc_anchor(frames=("15m", "1h"), market=(market_type or "futures"))
        btc_strength = float(anch.get("strength", 0.0) or 0.0)
        btc_dir = str(anch.get("direction", "") or "").upper() or None

        bz = float(budget_usd if budget_usd is not None else getattr(config, "MAX_TRADE_BUDGET", 100.0))
        if bz < 50.0:
            bz = 50.0

        ready: List[Dict[str, Any]] = []
        for item in results:
            plan_item = await _build_ready_plan(
                item=item,
                market_type=(market_type or "futures").lower(),
                budget_usd=bz,
                btc_strength=btc_strength,
                btc_dir=btc_dir
            )
            ready.append(plan_item)

        resp: Dict[str, Any] = {
            "strategy": {
                "name": _STRATEGY_META["name"],
                "version": _STRATEGY_META["version"],
                "git_commit": _STRATEGY_META["git_commit"],
                "req_hash": _STRATEGY_META["req_hash"],
            },
            "ready": ready
        }
        if include_results:
            resp["results"] = results
        return resp

    except Exception as e:
        fb = await fallback_scan_manual("BTCUSDT")
        return {"error": str(e), "results": fb, "ready": []}


