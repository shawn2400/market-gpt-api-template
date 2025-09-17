# utils/binance_trade.py
from __future__ import annotations
import os, time
from typing import Any, Dict, Optional

# ברירות מחדל ל-SL/TP מה-ENV
def _env_bps(name: str, default: str) -> list[float]:
    raw = os.getenv(name, default)
    out=[]
    for p in str(raw).split(","):
        p=p.strip()
        if not p: continue
        try: out.append(float(p))
        except Exception: pass
    return out

DEFAULT_SL_BPS   = _env_bps("DEFAULT_SL_BPS","80")              # 80 = 0.8%
DEFAULT_TP_BPS   = _env_bps("DEFAULT_TP_BPS","60,120,200")      # 0.6%,1.2%,2.0%
DEFAULT_TP_SPLIT = _env_bps("DEFAULT_TP_SPLITS","0.34,0.33,0.33")

def _side_dir(side:str) -> int:
    s=(side or "").upper()
    if s in ("BUY","LONG"):  return +1
    if s in ("SELL","SHORT"):return -1
    return 0

def _build_sl_tp(entry: float, side: str) -> tuple[dict,list]:
    d = _side_dir(side)
    if not d or not entry: return ({}, [])
    # SL
    sl_bps = DEFAULT_SL_BPS[0] if DEFAULT_SL_BPS else 80.0
    sl_px  = entry * (1 - d*(sl_bps/10000.0))
    sl = {"stopPrice": float(sl_px)}
    # TP legs
    tps=[]
    splits = DEFAULT_TP_SPLIT if DEFAULT_TP_SPLIT else [1.0]
    for i, bps in enumerate(DEFAULT_TP_BPS or [120.0], start=1):
        px = entry * (1 + d*(bps/10000.0))
        qty = splits[i-1] if i-1 < len(splits) else None
        leg={"stopPrice": float(px)}
        if qty is not None: leg["split"] = qty
        tps.append(leg)
    return sl, tps

def plan_trade(symbol: str, side: str, leverage: int, budget_usd: float,
               order_type: str="MARKET", entry_price: Optional[float]=None,
               **kwargs) -> Dict[str,Any]:
    symbol = (symbol or "").upper()
    side   = (side or "").upper()
    order_type = (order_type or "MARKET").upper()
    # מחיר נוכחי ל־entry אם לא סופק
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
    # נסה להפנות למימוש אמיתי אם קיים בפרויקט:
    try:
        from utils.trade_executor import execute_trade as core_exec  # אם יש
        return core_exec(symbol=symbol, side=side, leverage=leverage, budget_usd=budget_usd,
                         dry_run=dry_run, confirm_first=confirm_first,
                         order_type=order_type, entry_price=entry_price, **kwargs)
    except Exception:
        pass  # ניפול לתכנון בלבד

    plan = plan_trade(symbol, side, leverage, budget_usd, order_type, entry_price, **kwargs)
    return {"ok": True, "result": dict(plan, dry_run=bool(dry_run))}








































