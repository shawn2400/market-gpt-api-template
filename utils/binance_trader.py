# utils/binance_trade.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import os, time, re
from typing import Any, Dict, Optional, List

# ── ENV defaults ──────────────────────────────────────────────────────────────
def _env_list_floats(name: str, default_csv: str) -> List[float]:
    raw = os.getenv(name, default_csv)
    out: List[float] = []
    for p in str(raw).split(","):
        p = p.strip()
        if not p: continue
        try: out.append(float(p))
        except Exception: pass
    return out

DEFAULT_SL_BPS   = _env_list_floats("DEFAULT_SL_BPS",   "80")            # 0.8%
DEFAULT_TP_BPS   = _env_list_floats("DEFAULT_TP_BPS",   "60,120,200")    # 0.6/1.2/2.0%
DEFAULT_TP_SPLIT = _env_list_floats("DEFAULT_TP_SPLITS","0.34,0.33,0.33")

LADDER_TP_ENABLE          = os.getenv("LADDER_TP_ENABLE","1") in ("1","true","yes","on")
LADDER_TP_KIND            = os.getenv("LADDER_TP_KIND","TAKE_PROFIT_MARKET").upper()
LADDER_TP_DEFAULT_PCTS    = os.getenv("LADDER_TP_DEFAULT_PCTS","1.8,3.2,5.5")
LADDER_TP_DEFAULT_SPLITS  = os.getenv("LADDER_TP_DEFAULT_SPLITS","0.4,0.35,0.25")
LADDER_TP_MAX_LEVELS      = int(os.getenv("LADDER_TP_MAX_LEVELS","5"))
TP_LADDER_COOLDOWN_SEC    = int(os.getenv("TP_LADDER_COOLDOWN_SEC","60"))

ORDER_ID_PREFIX           = os.getenv("ORDER_ID_PREFIX","ALG")
CANCEL_PREFIX_OVERRIDE    = os.getenv("CANCEL_PREFIX_OVERRIDE","")
CANCEL_ONLY_PREFIXED_ORDERS = os.getenv("CANCEL_ONLY_PREFIXED_ORDERS","0") in ("1","true","yes","on")

# ── COID helpers ──────────────────────────────────────────────────────────────
_COID_SAFE = re.compile(r"[^A-Z0-9_]+")

def _sanitize_coid(x: str) -> str:
    return _COID_SAFE.sub("", (x or "").upper())[:64] or "COID"

def _coid(kind: str, symbol: str) -> str:
    base = (ORDER_ID_PREFIX or "ALG").upper()
    return _sanitize_coid(f"{base}_{kind}_{symbol}_{int(time.time()*1000)}")

def _kind_from_kwargs(kwargs: Dict[str, Any]) -> str:
    t = str(kwargs.get("type") or "").upper()
    if t.startswith("TAKE_PROFIT"): return "TP"
    if t.startswith("STOP"): return "SL"
    if t == "LIMIT": return "LMT"
    if t == "MARKET": return "MKT"
    return t or "ORD"

# ── Planning helpers ──────────────────────────────────────────────────────────
def _side_dir(side:str) -> int:
    s=(side or "").upper()
    if s in ("BUY","LONG"):  return +1
    if s in ("SELL","SHORT"):return -1
    return 0

def _build_sl_tp(entry: float, side: str) -> tuple[dict,List[dict]]:
    d = _side_dir(side)
    if not d or not entry: return ({}, [])
    # SL
    sl_bps = DEFAULT_SL_BPS[0] if DEFAULT_SL_BPS else 80.0
    sl_px  = entry * (1 - d*(sl_bps/10000.0))
    sl = {"stopPrice": float(sl_px)}
    # TP legs
    tps: List[dict] = []
    splits = DEFAULT_TP_SPLIT if DEFAULT_TP_SPLIT else [1.0]
    for i, bps in enumerate(DEFAULT_TP_BPS or [120.0], start=1):
        px = entry * (1 + d*(bps/10000.0))
        leg={"stopPrice": float(px)}
        if i-1 < len(splits):
            leg["split"] = splits[i-1]
        tps.append(leg)
    return sl, tps

def plan_trade(symbol: str, side: str, leverage: int, budget_usd: float,
               order_type: str="MARKET", entry_price: Optional[float]=None,
               **kwargs) -> Dict[str,Any]:
    symbol = (symbol or "").upper()
    side   = (side or "").upper()
    order_type = (order_type or "MARKET").upper()
    price = entry_price
    if not price:
        try:
            import requests
            base = os.getenv("INTERNAL_BASE", "http://127.0.0.1:10000")
            r = requests.get(f"{base}/price/{symbol}", timeout=2.5)
            if r.ok: price = float(r.json().get("price") or 0.0)
        except Exception:
            price = 0.0
    sl, tps = _build_sl_tp(float(price or 0.0), side)
    plan = {
        "symbol": symbol, "side": side, "leverage": int(leverage),
        "order_type": order_type, "entry_price": price,
        "sl": sl, "tp": tps,
        "budget_usd": float(budget_usd),
        "eta": {"entry_sec": 5, "tp1_sec": 300, "tp2_sec": 900, "tp3_sec": 1800},
        "probs": {"overall": 0.62, "tp1": 0.7, "tp2": 0.5, "tp3": 0.3},
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "trade_kind": "Futures",
    }
    return plan

def execute_trade(symbol: str, side: str, leverage: int, budget_usd: float,
                  dry_run: bool=True, confirm_first: bool=True,
                  order_type: str="MARKET", entry_price: Optional[float]=None,
                  **kwargs) -> Dict[str,Any]:
    """
    API שמספק routes.executor / routes.trade.
    אם יש לך מימוש פנימי אמיתי, אפשר להחליף פה (או לייבא).
    """
    try:
        from utils.trade_executor import execute_trade as core_exec  # אם יש
        return core_exec(symbol=symbol, side=side, leverage=leverage, budget_usd=budget_usd,
                         dry_run=dry_run, confirm_first=confirm_first,
                         order_type=order_type, entry_price=entry_price, **kwargs)
    except Exception:
        pass  # ניפול לתכנון בלבד

    plan = plan_trade(symbol, side, leverage, budget_usd, order_type, entry_price, **kwargs)
    return {"ok": True, "result": dict(plan, dry_run=bool(dry_run))}







































