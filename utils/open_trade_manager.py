# utils/open_trade_manager.py
from __future__ import annotations
import os, time, logging, requests, asyncio
from typing import Dict, Any, List, Optional
import pandas as pd

from utils import config as cfg
from utils.indicators import prepare_indicators_for_backtest
from utils.ws_fallback import get_price, is_price_fresh
from utils.precision_utils import apply_price_tick_side

# עטיפות בטוחות להזמנות
from utils.order_hygiene import (
    place_stop_market_safe,
    place_take_profit_safe,
)

# פונקציות מבינאנס
from utils.binance_client import (
    futures_mark_price,
    get_open_orders,
    cancel_order,
    futures_position_risk,
)

logger = logging.getLogger("algogpt.open_trade_manager")

# =============================================================================
# ENV Helpers
# =============================================================================
def _as_bool(s: Optional[str], default=False) -> bool:
    return str(s).strip().lower() in {"1","true","yes","on"} if s else default

def _as_float(s: Optional[str], default: float) -> float:
    try: return float(str(s).strip())
    except: return default

def _as_int(s: Optional[str], default: int) -> int:
    try: return int(str(s).strip())
    except: return default

# =============================================================================
# Parameters (configurable via ENV)
# =============================================================================
CHOP_DETECT_ENABLE     = _as_bool(os.getenv("CHOP_DETECT_ENABLE", "true"), True)
CHOP_ADX_MAX           = _as_float(os.getenv("CHOP_ADX_MAX", "18"), 18.0)
CHOP_MACD_HIST_ABS_MAX = _as_float(os.getenv("CHOP_MACD_HIST_ABS_MAX", "0.05"), 0.05)
CHOP_BB_WIDTH_PCT_MAX  = _as_float(os.getenv("CHOP_BB_WIDTH_PCT_MAX", "0.9"), 0.9)
CHOP_MIN_BARS          = _as_int(os.getenv("CHOP_MIN_BARS", "6"), 6)
CHOP_ACTION            = (os.getenv("CHOP_ACTION", "to_breakeven") or "to_breakeven").strip()
CHOP_PARTIAL_PCT       = _as_float(os.getenv("CHOP_PARTIAL_PCT", "0.33"), 0.33)

BE_ARM_PCT             = _as_float(os.getenv("BE_ARM_PCT", "1.6"), 1.6)
TRAIL_ATR_MULT         = _as_float(os.getenv("TRAIL_ATR_MULT", str(getattr(cfg, "STOP_LOSS_ATR_MULTIPLIER", 1.5))), 1.5)
MOMENTUM_TP_SHIFT_ATR  = _as_float(os.getenv("MOMENTUM_TP_SHIFT", "0.5"), 0.5)

MANAGER_COOLDOWN_SEC   = _as_int(os.getenv("MANAGER_COOLDOWN_SEC", "45"), 45)

GRID_ENABLE  = _as_bool(os.getenv("GRID_ENABLE", "true"), True)
GRID_TP1_ATR = _as_float(os.getenv("GRID_TP1_ATR", "1.0"), 1.0)
GRID_TP2_ATR = _as_float(os.getenv("GRID_TP2_ATR", "1.8"), 1.8)
GRID_TP3_ATR = _as_float(os.getenv("GRID_TP3_ATR", "2.6"), 2.6)
GRID_SPLIT_1 = _as_float(os.getenv("GRID_SPLIT_1", "0.33"), 0.33)
GRID_SPLIT_2 = _as_float(os.getenv("GRID_SPLIT_2", "0.33"), 0.33)
GRID_SPLIT_3 = _as_float(os.getenv("GRID_SPLIT_3", "0.34"), 0.34)

FUTURES_BASE = getattr(cfg, "BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com")
KL_INTERVAL  = os.getenv("MANAGER_SCAN_INTERVAL", getattr(cfg, "DEFAULT_INTERVAL", "15m"))
KL_LIMIT     = _as_int(os.getenv("MANAGER_SCAN_LIMIT", "200"), 200)

_last_touch: Dict[str,float] = {}

# =============================================================================
# Helpers
# =============================================================================
def _fresh_price(symbol: str) -> Optional[float]:
    try:
        if is_price_fresh(symbol, max_age_sec=int(os.getenv("PRICE_MAX_AGE_SEC","10"))):
            return get_price(symbol)
    except Exception as e:
        logger.warning({"event":"ws_price_failed","symbol":symbol,"err":str(e)})
    try:
        return float(futures_mark_price(symbol) or 0.0)
    except Exception as e:
        logger.warning({"event":"rest_price_failed","symbol":symbol,"err":str(e)})
        return None

def _pct(a: float, b: float) -> float:
    return (b/a - 1.0)*100.0 if a else 0.0

def _bb_width_pct(row: Dict[str,Any]) -> float:
    mid = float(row.get("bb_mid") or 0.0)
    up  = float(row.get("bb_upper") or 0.0)
    lo  = float(row.get("bb_lower") or 0.0)
    return (up-lo)/mid*100.0 if mid>0 else 0.0

def _momentum_ok(side: str, row: Dict[str,Any]) -> bool:
    adx = float(row.get("adx") or 0.0)
    macd_hist = float(row.get("macd_hist") or 0.0)
    return adx>=25.0 and ((macd_hist>0 and side.upper() in ("BUY","LONG")) or
                          (macd_hist<0 and side.upper() in ("SELL","SHORT")))

def _chop_now(window: List[Dict[str,Any]]) -> bool:
    if not CHOP_DETECT_ENABLE or len(window)<CHOP_MIN_BARS: return False
    last = window[-CHOP_MIN_BARS:]
    adx_ok  = all(float(r.get("adx") or 0.0)<CHOP_ADX_MAX for r in last)
    macd_ok = all(abs(float(r.get("macd_hist") or 0.0))<=CHOP_MACD_HIST_ABS_MAX for r in last)
    bb_ok   = all(_bb_width_pct(r)<=CHOP_BB_WIDTH_PCT_MAX for r in last)
    return adx_ok and macd_ok and bb_ok

def _side_to_close(side: str) -> str:
    return "SELL" if side.upper() in ("BUY","LONG") else "BUY"

async def _klines_df(symbol: str) -> pd.DataFrame:
    url = f"{FUTURES_BASE}/fapi/v1/klines"
    r = requests.get(url, params={"symbol":symbol,"interval":KL_INTERVAL,"limit":KL_LIMIT}, timeout=10)
    r.raise_for_status()
    arr = r.json()
    cols=["open_time","open","high","low","close","volume","close_time","qv","nTrades","taker_base","taker_quote","x"]
    df = pd.DataFrame(arr, columns=cols[:len(arr[0])])
    for c in ("open","high","low","close","volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df

# =============================================================================
# Grid TP Logic
# =============================================================================
def _ensure_grid_orders(sym: str, side_u: str, entry: float, atr: float, qty: float) -> Optional[str]:
    try:
        oo = get_open_orders(sym) or []
    except Exception as e:
        logger.warning({"event":"get_open_orders_failed","symbol":sym,"err":str(e)})
        oo=[]
    ro_tp=[o for o in oo if str(o.get("reduceOnly","")).lower() in ("true","1") and str(o.get("type","")).upper().startswith("TAKE_PROFIT")]
    if ro_tp: return None

    close_side=_side_to_close(side_u)
    sgn=1.0 if side_u in ("BUY","LONG") else -1.0
    targets=[entry+sgn*GRID_TP1_ATR*atr, entry+sgn*GRID_TP2_ATR*atr, entry+sgn*GRID_TP3_ATR*atr]
    splits=[GRID_SPLIT_1, GRID_SPLIT_2, GRID_SPLIT_3]
    labels=["GRID_TP1_RO","GRID_TP2_RO","GRID_TP3_RO"]

    changed=[]
    for i,(tgt,pct,lab) in enumerate(zip(targets,splits,labels)):
        if pct<=0: continue
        q=max(0.0, qty*pct)
        px,_=apply_price_tick_side(tgt, sym, close_side)
        try:
            idp=f"grid:{sym}:{i}:{close_side}:{float(px):.8f}:{float(q):.8f}"
            place_take_profit_safe(symbol=sym, side=close_side, stop_price=float(px), qty=float(q),
                                   reduce_only=True, idp_key=idp)
            changed.append(lab)
        except Exception as e:
            logger.warning({"event":"grid_tp_place_failed","symbol":sym,"stage":lab,"err":str(e)})
    return ",".join(changed) if changed else None

# =============================================================================
# Positions
# =============================================================================
def _positions() -> List[Dict[str,Any]]:
    try:
        pos=futures_position_risk() or []
        out=[]
        for p in pos:
            amt=float(p.get("positionAmt") or 0.0)
            if abs(amt)<=0: continue
            sym=str(p.get("symbol") or "").upper()
            entry=float(p.get("entryPrice") or 0.0)
            lev=float(p.get("leverage") or 1.0)
            side="LONG" if amt>0 else "SHORT"
            out.append({"symbol":sym,"side":side,"qty":abs(amt),"entry":entry,"leverage":lev})
        return out
    except Exception as e:
        logger.warning({"event":"positions_fetch_failed","err":str(e)})
        return []

# =============================================================================
# Manage One Symbol
# =============================================================================
async def _manage_symbol(sym: str, side: str, qty: float, entry: float) -> Dict[str,Any]:
    side_u=side.upper()
    close_side=_side_to_close(side_u)

    if (time.time()-_last_touch.get(sym,0.0))<MANAGER_COOLDOWN_SEC:
        return {"symbol":sym,"skipped":"cooldown"}

    px=_fresh_price(sym)
    if not px: return {"symbol":sym,"skipped":"no_price"}

    df=await _klines_df(sym)
    ind=prepare_indicators_for_backtest(df)
    if ind.empty: return {"symbol":sym,"skipped":"no_indicators"}
    tail=[ind.iloc[i].to_dict() for i in range(max(0,len(ind)-50),len(ind))]
    row=tail[-1]
    atr=float(row.get("atr") or 0.0)
    adx=float(row.get("adx") or 0.0)
    macd_hist=float(row.get("macd_hist") or 0.0)
    if atr<=0.0: return {"symbol":sym,"skipped":"atr_zero"}

    grid_info=None
    if GRID_ENABLE:
        try: grid_info=_ensure_grid_orders(sym, side_u, entry, atr, qty)
        except Exception as e: logger.warning({"event":"grid_ensure_error","symbol":sym,"err":str(e)})

    # Dynamic SL (Breakeven + Trailing ATR)
    if side_u in ("BUY","LONG"):
        trail_sl_raw=px-(TRAIL_ATR_MULT*atr)
        be_px=max(entry, trail_sl_raw)
        desired_sl,_=apply_price_tick_side(be_px, sym, close_side)
    else:
        trail_sl_raw=px+(TRAIL_ATR_MULT*atr)
        be_px=min(entry, trail_sl_raw)
        desired_sl,_=apply_price_tick_side(be_px, sym, close_side)

    # Dynamic TP (momentum shift)
    sgn=1.0 if side_u in ("BUY","LONG") else -1.0
    base_tp=entry+sgn*2.0*atr
    tp_shift=(MOMENTUM_TP_SHIFT_ATR*atr) if _momentum_ok(side_u,row) else 0.0
    desired_tp,_=apply_price_tick_side(base_tp+tp_shift, sym, close_side)

    # Chop zone → move SL to BE
    is_chop=_chop_now(tail)
    pnl_pct=_pct(entry,px) if side_u in ("BUY","LONG") else _pct(px,entry)
    chop_action_taken=None
    if is_chop and CHOP_ACTION=="to_breakeven" and pnl_pct>=0.0:
        desired_sl,_=apply_price_tick_side(entry, sym, close_side)
        chop_action_taken="SL->BE"

    if not _as_bool(os.getenv("ALLOW_MANAGE_OPEN_TRADES","true"),True):
        return {"symbol":sym,"skipped":"ALLOW_MANAGE_OPEN_TRADES=false"}

    errors=[]
    changed=False
    try: oo=get_open_orders(sym) or []
    except Exception: oo=[]
    sl_order_id=None; tp_orders=[]
    for o in oo:
        if str(o.get("reduceOnly","")).lower() not in ("true","1"): continue
        ty=str(o.get("type","")).upper()
        if ty.startswith("STOP"): sl_order_id=o.get("orderId")
        elif ty.startswith("TAKE_PROFIT"): tp_orders.append(o)

    try:
        if sl_order_id:
            try: cancel_order(sym, order_id=sl_order_id)
            except Exception: pass
        idp=f"sl:update:{sym}:{close_side}:{float(desired_sl):.8f}:{float(qty):.8f}"
        place_stop_market_safe(symbol=sym, side=close_side, stop_price=float(desired_sl),
                               qty=float(qty), reduce_only=True, idp_key=idp)
        changed=True
    except Exception as e: errors.append(f"sl_update_failed:{e}")

    if not GRID_ENABLE and not tp_orders:
        try:
            idp=f"tp:global:{sym}:{close_side}:{float(desired_tp):.8f}:{float(qty):.8f}"
            place_take_profit_safe(symbol=sym, side=close_side, stop_price=float(desired_tp),
                                   qty=float(qty), reduce_only=True, idp_key=idp)
            changed=True
        except Exception as e: errors.append(f"tp_update_failed:{e}")

    _last_touch[sym]=time.time()
    return {
        "symbol":sym,"side":side_u,"entry":entry,"price":px,
        "pnl_pct":round(pnl_pct,4),"adx":round(adx,3),"macd_hist":round(macd_hist,5),
        "atr":round(atr,6),"is_chop":bool(is_chop),
        "desired_sl":float(desired_sl),"desired_tp":float(desired_tp),
        "grid":grid_info,"changed":changed,"chop_action":chop_action_taken,"errors":errors,
    }

# =============================================================================
# Public API
# =============================================================================
async def manage_open_trades() -> Dict[str,Any]:
    pos=_positions()
    if not pos:
        return {"ok":True,"managed":0,"details":[],"note":"no_positions"}
    details=[]
    for p in pos:
        try:
            res=await _manage_symbol(p["symbol"], p["side"], float(p["qty"]), float(p["entry"]))
            details.append(res)
        except Exception as e:
            details.append({"symbol":p.get("symbol","?"),"error":str(e)})
    changed=sum(1 for d in details if d.get("changed"))
    return {"ok":True,"managed":len(details),"changed":changed,"details":details}







