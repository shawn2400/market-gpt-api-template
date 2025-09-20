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
        if not p:
            continue
        try:
            out.append(float(p))
        except Exception:
            pass
    return out

def _env_bool(name: str, default: str = "0") -> bool:
    return (os.getenv(name, default) or "").strip().lower() in ("1", "true", "yes", "on")

DEFAULT_SL_BPS   = _env_list_floats("DEFAULT_SL_BPS",   "80")            # 0.8%
DEFAULT_TP_BPS   = _env_list_floats("DEFAULT_TP_BPS",   "60,120,200")    # 0.6/1.2/2.0%
DEFAULT_TP_SPLIT = _env_list_floats("DEFAULT_TP_SPLITS","0.34,0.33,0.33")

LADDER_TP_ENABLE          = _env_bool("LADDER_TP_ENABLE", "1")
LADDER_TP_KIND            = (os.getenv("LADDER_TP_KIND","TAKE_PROFIT_MARKET") or "TAKE_PROFIT_MARKET").upper()
LADDER_TP_DEFAULT_PCTS    = os.getenv("LADDER_TP_DEFAULT_PCTS","1.8,3.2,5.5")
LADDER_TP_DEFAULT_SPLITS  = os.getenv("LADDER_TP_DEFAULT_SPLITS","0.4,0.35,0.25")
LADDER_TP_MAX_LEVELS      = int(os.getenv("LADDER_TP_MAX_LEVELS","5") or 5)
TP_LADDER_COOLDOWN_SEC    = int(os.getenv("TP_LADDER_COOLDOWN_SEC","60") or 60)

ORDER_ID_PREFIX             = os.getenv("ORDER_ID_PREFIX","ALG") or "ALG"
CANCEL_PREFIX_OVERRIDE      = os.getenv("CANCEL_PREFIX_OVERRIDE","") or ""
CANCEL_ONLY_PREFIXED_ORDERS = _env_bool("CANCEL_ONLY_PREFIXED_ORDERS","0")

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
    if t.startswith("STOP"):        return "SL"
    if t == "LIMIT":                return "LMT"
    if t == "MARKET":               return "MKT"
    return t or "ORD"

# ── Planning helpers ──────────────────────────────────────────────────────────
def _side_dir(side: str) -> int:
    s = (side or "").upper()
    if s in ("BUY","LONG"):   return +1
    if s in ("SELL","SHORT"): return -1
    return 0

def _build_sl_tp(entry: float, side: str) -> tuple[dict, List[dict]]:
    d = _side_dir(side)
    if not d or not entry:
        return ({}, [])
    # SL
    sl_bps = DEFAULT_SL_BPS[0] if DEFAULT_SL_BPS else 80.0
    sl_px  = entry * (1 - d*(sl_bps / 10000.0))
    sl = {"stopPrice": float(sl_px)}
    # TP legs
    tps: List[dict] = []
    splits = DEFAULT_TP_SPLIT if DEFAULT_TP_SPLIT else [1.0]
    for i, bps in enumerate(DEFAULT_TP_BPS or [120.0], start=1):
        px = entry * (1 + d*(bps / 10000.0))
        leg = {"stopPrice": float(px)}
        if i-1 < len(splits):
            leg["split"] = splits[i-1]
        tps.append(leg)
    return sl, tps

def plan_trade(
    symbol: str,
    side: str,
    leverage: int,
    budget_usd: float,
    order_type: str = "MARKET",
    entry_price: Optional[float] = None,
    **kwargs
) -> Dict[str, Any]:
    symbol = (symbol or "").upper()
    side   = (side or "").upper()
    order_type = (order_type or "MARKET").upper()
    price = entry_price
    if price is None:
        # Best-effort local price endpoint; אם אין — נשתמש ב־0.0 (התכנון עדיין יוחזר)
        try:
            import requests  # type: ignore
            base = os.getenv("INTERNAL_BASE", "http://127.0.0.1:10000")
            r = requests.get(f"{base}/price/{symbol}", timeout=2.5)
            if r.ok:
                price = float(r.json().get("price") or 0.0)
        except Exception:
            price = 0.0
    sl, tps = _build_sl_tp(float(price or 0.0), side)
    plan = {
        "symbol": symbol,
        "side": side,
        "leverage": int(leverage),
        "order_type": order_type,
        "entry_price": price,
        "sl": sl,
        "tp": tps,
        "budget_usd": float(budget_usd),
        # הערכות דיפולט (דינמיקה אמיתית מחושבת חיצונית במודולים ייעודיים)
        "eta":   {"entry_sec": 5, "tp1_sec": 300, "tp2_sec": 900, "tp3_sec": 1800},
        "probs": {"overall": 0.62, "tp1": 0.70, "tp2": 0.50, "tp3": 0.30},
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "trade_kind": "Futures",
    }
    return plan

# ── Public API (compat) ───────────────────────────────────────────────────────
def execute_trade(
    symbol: str,
    side: str,
    leverage: int,
    budget_usd: float,
    *,
    dry_run: bool = True,
    confirm_first: bool = True,
    order_type: str = "MARKET",
    entry_price: Optional[float] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    API תואם לשימושים קיימים (routes.executor / routes.trade).
    אם יש utils.trade_executor.execute_trade – נשתמש בו; אחרת מחזירים תוכנית בלבד (dry-run).
    אין תלות בהודעות טלגרם כאן (האישורים/אוטומציה מטופלים חיצונית, דינמית).
    """
    try:
        # אם קיים מימוש פנימי – נשתמש בו
        from utils.trade_executor import execute_trade as core_exec  # type: ignore
        return core_exec(
            symbol=symbol, side=side, leverage=leverage, budget_usd=budget_usd,
            dry_run=dry_run, confirm_first=confirm_first,
            order_type=order_type, entry_price=entry_price, **kwargs
        )
    except Exception:
        # fallback: תכנון בלבד
        plan = plan_trade(symbol, side, leverage, budget_usd, order_type, entry_price, **kwargs)
        return {"ok": True, "result": dict(plan, dry_run=bool(dry_run))}

async def execute_order(*args, **kwargs) -> Dict[str, Any]:
    """
    Shim אסינכרוני לתאימות: חלק מהראוטרים מצפים ל־utils.binance_trade.execute_order.
    אם python-binance/לקוח זמינים – ננסה לבצע הזמנה; אחרת נחזיר תשובת shim ברורה.
    """
    # נסה להאציל ל־utils.binance_client.futures_create_order אם אפשר
    try:
        from utils.binance_client import futures_create_order  # type: ignore
        res = futures_create_order(**kwargs)
        if isinstance(res, dict):
            return res
        return {"ok": True, "res": res}
    except Exception as e:
        return {"ok": False, "reason": "binance_trade shim", "error": str(e)}








































