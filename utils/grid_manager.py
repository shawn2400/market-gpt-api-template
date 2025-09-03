# utils/grid_manager.py
from __future__ import annotations
import os, time, json, logging
from typing import Optional, Dict, Any, List, Tuple

import pandas as pd
from utils import config as cfg
from utils.indicators import prepare_indicators_for_backtest
from utils.ws_fallback import get_price, is_price_fresh
from utils.precision_utils import apply_price_tick_side
from utils.alerts import tg_grid
from utils.account_clients import get_account_client  # חדש – לכל חשבון client משלו

logger = logging.getLogger("algogpt.grid")

# ──────────────────────────────────────────────────────────────
# עזרי ENV
# ──────────────────────────────────────────────────────────────
def _as_bool(s: Optional[str], default=False) -> bool:
    return str(s).strip().lower() in {"1","true","yes","on"} if s is not None else default

def _as_float(s: Optional[str], default: float) -> float:
    try: return float(str(s).strip())
    except: return default

GRID_ENABLE          = _as_bool(os.getenv("GRID_ENABLE","true"), True)
TP1_ATR              = _as_float(os.getenv("GRID_TP1_ATR","1.0"), 1.0)
TP2_ATR              = _as_float(os.getenv("GRID_TP2_ATR","1.8"), 1.8)
TP3_ATR              = _as_float(os.getenv("GRID_TP3_ATR","2.6"), 2.6)
SPLIT_1              = _as_float(os.getenv("GRID_SPLIT_1","0.33"), 0.33)
SPLIT_2              = _as_float(os.getenv("GRID_SPLIT_2","0.33"), 0.33)
SPLIT_3              = _as_float(os.getenv("GRID_SPLIT_3","0.34"), 0.34)

TRAIL_ATR_MULT       = _as_float(os.getenv("TRAIL_ATR_MULT","1.5"), 1.5)
BE_ARM_PCT           = _as_float(os.getenv("BE_ARM_PCT","1.6"), 1.6)

STREAM_TP_BE         = _as_bool(os.getenv("STREAM_TP_BE","true"), True)
TP_LOCK_STAGE2_ATR   = _as_float(os.getenv("TP_LOCK_STAGE2_ATR","0.5"), 0.5)

MANAGER_COOLDOWN_SEC = int(os.getenv("MANAGER_COOLDOWN_SEC","45") or 45)

# ──────────────────────────────────────────────────────────────
# פונקציות עזר פנימיות
# ──────────────────────────────────────────────────────────────
def _split_qtys(total_qty: float) -> Tuple[float,float,float]:
    a = max(0.0, total_qty * SPLIT_1)
    b = max(0.0, total_qty * SPLIT_2)
    c = max(0.0, total_qty * SPLIT_3)
    s = a+b+c
    if abs(s-total_qty) > 1e-9:
        c += (total_qty - s)
    return (a,b,max(0.0,c))

def _close_side(position_side: str) -> str:
    return "SELL" if position_side.upper() in ("LONG","BUY") else "BUY"

def _align(symbol: str, px: float, side: str) -> float:
    qpx, _ = apply_price_tick_side(px, symbol, side)
    return float(qpx)

# ──────────────────────────────────────────────────────────────
# מטרות TP/SL
# ──────────────────────────────────────────────────────────────
def compute_targets(entry: float, atr: float, side: str) -> Tuple[float,float,float,float]:
    if atr <= 0 or entry <= 0:
        raise ValueError("bad entry/atr")
    s = side.upper()
    if s in ("BUY","LONG"):
        tp1 = entry + TP1_ATR*atr
        tp2 = entry + TP2_ATR*atr
        tp3 = entry + TP3_ATR*atr
        sl0 = entry - TRAIL_ATR_MULT*atr
    else:
        tp1 = entry - TP1_ATR*atr
        tp2 = entry - TP2_ATR*atr
        tp3 = entry - TP3_ATR*atr
        sl0 = entry + TRAIL_ATR_MULT*atr
    return (tp1,tp2,tp3,sl0)

# ──────────────────────────────────────────────────────────────
# Grid ראשי – עם account_id
# ──────────────────────────────────────────────────────────────
async def start_grid_for_position(symbol: str, account_id: str, *, use_indicators: bool=True) -> Dict[str, Any]:
    """
    מפעיל גריד חי בחשבון שנבחר (account_id).
    """
    if not GRID_ENABLE:
        return {"ok": False, "error": "GRID_ENABLE=false"}

    client = get_account_client(account_id, market="futures")
    if not client:
        return {"ok": False, "error": f"account {account_id} not found"}

    sym = symbol.upper().strip()

    # פוזיציות פתוחות
    try:
        r = client.request("GET", "/fapi/v2/positionRisk", signed=True)
        positions = r.json()
    except Exception as e:
        return {"ok": False, "error": f"position_risk_failed:{e}"}

    pos = None
    for p in positions:
        if p.get("symbol") == sym and abs(float(p.get("positionAmt") or 0)) > 0:
            pos = p
            break

    if not pos:
        return {"ok": False, "error": "no_open_position"}

    side = "LONG" if float(pos.get("positionAmt")) > 0 else "SHORT"
    close_side = _close_side(side)
    qty_total = abs(float(pos.get("positionAmt") or 0))
    entry = float(pos.get("entryPrice") or 0.0)
    if qty_total <= 0 or entry <= 0:
        return {"ok": False, "error": "bad_qty_or_entry"}

    # ATR
    atr = 0.0
    if use_indicators:
        try:
            url = f"{cfg.BINANCE_FUTURES_HTTP_BASE}/fapi/v1/klines"
            import requests
            r = requests.get(url, params={"symbol":sym, "interval":cfg.DEFAULT_INTERVAL, "limit":200}, timeout=10)
            arr = r.json()
            df = pd.DataFrame(arr, columns=["open_time","open","high","low","close","volume","x","y","z","a","b","c"])
            for c in ("open","high","low","close","volume"):
                df[c] = pd.to_numeric(df[c], errors="coerce")
            ind = prepare_indicators_for_backtest(df)
            atr = float(ind.iloc[-1]["atr"])
        except Exception as e:
            logger.warning({"event":"grid_atr_failed","err":str(e)})
    if atr <= 0:
        atr = max(0.001*entry, 1e-6)

    # מטרות
    tp1,tp2,tp3,sl0 = compute_targets(entry, atr, side)
    tp1 = _align(sym,tp1,close_side)
    tp2 = _align(sym,tp2,close_side)
    tp3 = _align(sym,tp3,close_side)
    sl0 = _align(sym,sl0,close_side)

    q1,q2,q3 = _split_qtys(qty_total)

    placed = {}
    errors: List[str] = []

    try:
        # מציבים SL
        placed["sl"] = client.request("POST","/fapi/v1/order",signed=True,params={
            "symbol": sym,"side": close_side,"type":"STOP_MARKET",
            "stopPrice": sl0,"quantity": qty_total,"reduceOnly":"true"
        }).json()
    except Exception as e:
        errors.append(f"sl_failed:{e}")

    # מציבים TPs
    for i,(px,qty) in enumerate([(tp1,q1),(tp2,q2),(tp3,q3)], start=1):
        if qty > 0:
            try:
                placed[f"tp{i}"] = client.request("POST","/fapi/v1/order",signed=True,params={
                    "symbol": sym,"side": close_side,"type":"TAKE_PROFIT_MARKET",
                    "stopPrice": px,"quantity": qty,"reduceOnly":"true",
                    "newClientOrderId": f"GRID_{sym}_{side}_TP{i}_{int(time.time())}"
                }).json()
            except Exception as e:
                errors.append(f"tp{i}_failed:{e}")

    try:
        tg_grid(f"📊 Grid armed • {sym} {side} @ {entry}\nSL={sl0} | TP1={tp1}, TP2={tp2}, TP3={tp3}")
    except: pass

    return {"ok": len(errors)==0, "errors": errors, "placed": placed}





