# utils/grid_manager.py
from __future__ import annotations
import os, time, json, logging, asyncio
from typing import Optional, Dict, Any, List, Tuple

import pandas as pd

from utils import config as cfg
from utils.indicators import prepare_indicators_for_backtest
from utils.ws_fallback import get_price, is_price_fresh
from utils.precision_utils import apply_price_tick_side
from utils.alerts import tg_grid

logger = logging.getLogger("algogpt.grid")

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

TRAIL_ATR_MULT       = _as_float(os.getenv("TRAIL_ATR_MULT", str(getattr(cfg, "STOP_LOSS_ATR_MULTIPLIER", 1.5))), getattr(cfg, "STOP_LOSS_ATR_MULTIPLIER", 1.5))
BE_ARM_PCT           = _as_float(os.getenv("BE_ARM_PCT","1.6"), 1.6)

STREAM_TP_BE         = _as_bool(os.getenv("STREAM_TP_BE","true"), True)
TP_LOCK_STAGE2_ATR   = _as_float(os.getenv("TP_LOCK_STAGE2_ATR","0.5"), 0.5)

MANAGER_COOLDOWN_SEC = int(os.getenv("MANAGER_COOLDOWN_SEC","45") or 45)

REDIS_URL = os.getenv("REDIS_URL") or ""
NS = (os.getenv("REDIS_NAMESPACING") or "algogpt:v2").strip()
RKEY = f"{NS}:grid"

_redis = None
try:
    import redis  # type: ignore
    _redis = redis.from_url(REDIS_URL, decode_responses=True) if REDIS_URL else None
except Exception:
    _redis = None

_mem: Dict[str, Dict[str, Any]] = {}

from utils.binance_client import (
    futures_position_risk,
    place_stop_market,
    place_take_profit_market,
    futures_mark_price,
    get_open_orders,
    cancel_order,
    cancel_open_orders,
)

def _save_state(sym: str, st: Dict[str, Any]) -> None:
    st = dict(st or {})
    st["ts"] = time.time()
    _mem[sym] = st
    try:
        if _redis:
            _redis.hset(RKEY, sym, json.dumps(st, separators=(",",":")))
    except Exception as e:
        logger.warning({"event":"grid_state_redis_save_failed","symbol":sym,"err":str(e)})

def _load_state(sym: str) -> Optional[Dict[str, Any]]:
    if sym in _mem:
        return dict(_mem[sym])
    try:
        if _redis:
            raw = _redis.hget(RKEY, sym)
            if raw:
                st = json.loads(raw)
                _mem[sym] = st
                return dict(st)
    except Exception as e:
        logger.warning({"event":"grid_state_redis_load_failed","symbol":sym,"err":str(e)})
    return None

def _del_state(sym: str) -> None:
    _mem.pop(sym, None)
    try:
        if _redis: _redis.hdel(RKEY, sym)
    except Exception:
        pass

def _align(symbol: str, px: float, close_side: str) -> float:
    qpx, _ = apply_price_tick_side(px, symbol, close_side)
    return float(qpx)

def _split_qtys(total_qty: float) -> Tuple[float,float,float]:
    a = max(0.0, total_qty * SPLIT_1)
    b = max(0.0, total_qty * SPLIT_2)
    c = max(0.0, total_qty * SPLIT_3)
    s = a+b+c
    if s <= 0: return (0.0, 0.0, 0.0)
    if abs(s-total_qty) > 1e-9:
        c += (total_qty - s)
    return (a, b, max(0.0, c))

def _close_side(position_side: str) -> str:
    return "SELL" if position_side.upper() in ("LONG","BUY") else "BUY"

def _fresh_mark(symbol: str) -> Optional[float]:
    try:
        if is_price_fresh(symbol, max_age_sec=int(os.getenv("PRICE_MAX_AGE_SEC","10"))):
            return float(get_price(symbol) or 0.0)
        return float(futures_mark_price(symbol) or 0.0)
    except Exception:
        return None

def compute_targets(entry: float, atr: float, side: str) -> Tuple[float,float,float,float]:
    if atr <= 0 or entry <= 0: raise ValueError("bad entry/atr")
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
    return (float(tp1), float(tp2), float(tp3), float(sl0))

async def start_grid_for_position(symbol: str, *, use_indicators: bool=True) -> Dict[str, Any]:
    if not GRID_ENABLE:
        return {"ok": False, "error": "GRID_ENABLE=false"}
    symbol = symbol.upper().strip()

    pos = None
    try:
        for p in futures_position_risk() or []:
            if str(p.get("symbol")).upper() == symbol:
                amt = float(p.get("positionAmt") or 0.0)
                if abs(amt) > 0:
                    pos = p
                    break
    except Exception as e:
        return {"ok": False, "error": f"position_risk_failed:{e}"}
    if not pos:
        return {"ok": False, "error": "no_open_position"}

    side = "LONG" if float(pos.get("positionAmt") or 0.0) > 0 else "SHORT"
    close_side = _close_side(side)
    qty_total = abs(float(pos.get("positionAmt") or 0.0))
    entry = float(pos.get("entryPrice") or 0.0)
    if qty_total <= 0 or entry <= 0:
        return {"ok": False, "error": "bad_qty_or_entry"}

    atr = 0.0
    if use_indicators:
        try:
            import requests
            url = f"{cfg.BINANCE_FUTURES_HTTP_BASE}/fapi/v1/klines"
            r = requests.get(url, params={"symbol":symbol, "interval":cfg.DEFAULT_INTERVAL, "limit":200}, timeout=10)
            r.raise_for_status()
            arr = r.json()
            cols = ["open_time","open","high","low","close","volume","close_time","qv","nTrades","taker_base","taker_quote","x"]
            df = pd.DataFrame(arr, columns=cols[:len(arr[0])])
            for c in ("open","high","low","close","volume"): df[c] = pd.to_numeric(df[c], errors="coerce")
            ind = prepare_indicators_for_backtest(df)
            atr = float(ind.iloc[-1]["atr"])
        except Exception as e:
            logger.warning({"event":"grid_atr_failed","symbol":symbol,"err":str(e)})
    if atr <= 0:
        mk = _fresh_mark(symbol) or entry
        atr = max(0.001*mk, 1e-6)

    tp1, tp2, tp3, sl0 = compute_targets(entry, atr, side)
    tp1 = _align(symbol, tp1, close_side)
    tp2 = _align(symbol, tp2, close_side)
    tp3 = _align(symbol, tp3, close_side)
    sl0 = _align(symbol, sl0, close_side)

    q1,q2,q3 = _split_qtys(qty_total)
    eps = 1e-12
    q1 = q1 if q1 > eps else 0.0
    q2 = q2 if q2 > eps else 0.0
    q3 = q3 if q3 > eps else 0.0

    placed = {"sl":None,"tp1":None,"tp2":None,"tp3":None}
    errors: List[str] = []

    try:
        if sl0 > 0:
            placed["sl"] = place_stop_market(symbol, close_side, float(sl0), float(qty_total), reduce_only=True)
    except Exception as e:
        errors.append(f"sl_place_failed:{e}")

    def _cid(stage:int)->str:
        return f"GRID_{symbol}_{side}_TP{stage}_RO_{int(time.time())%1_000_000}"

    try:
        if q1 > 0:
            placed["tp1"] = place_take_profit_market(symbol, close_side, float(tp1), float(q1), reduce_only=True, client_order_id=_cid(1))
        if q2 > 0:
            placed["tp2"] = place_take_profit_market(symbol, close_side, float(tp2), float(q2), reduce_only=True, client_order_id=_cid(2))
        if q3 > 0:
            placed["tp3"] = place_take_profit_market(symbol, close_side, float(tp3), float(q3), reduce_only=True, client_order_id=_cid(3))
    except Exception as e:
        errors.append(f"tp_place_failed:{e}")

    state = {
        "symbol": symbol,
        "side": side,
        "close_side": close_side,
        "entry": entry,
        "atr": atr,
        "qty_total": qty_total,
        "splits": [q1,q2,q3],
        "targets": [tp1,tp2,tp3],
        "sl0": sl0,
        "filled": [False, False, False],
        "order_refs": placed,
        "created": time.time(),
        "last_touch": 0.0,
    }
    _save_state(symbol, state)

    try:
        if qty_total > 0:
            tg_grid(
                f"Grid armed • {symbol} {side}\n"
                f"SL: {sl0:.6f}\n"
                f"TP1: {tp1:.6f} ({q1:.4f}), TP2: {tp2:.6f} ({q2:.4f}), TP3: {tp3:.6f} ({q3:.4f})"
            )
    except Exception:
        pass

    ok = (placed["tp1"] or q1==0) and (placed["tp2"] or q2==0) and (placed["tp3"] or q3==0)
    return {"ok": bool(ok), "state": state, "errors": errors}

def on_user_stream_event(evt: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    try:
        if not evt or str(evt.get("e","")) != "ORDER_TRADE_UPDATE":
            return None
        o = evt.get("o") or {}
        status = str(o.get("X","")).upper()
        if status != "FILLED":
            return None
        symbol = str(o.get("s","")).upper()
        client_id = str(o.get("c",""))
        if not client_id.startswith("GRID_"):
            return None

        st = _load_state(symbol)
        if not st:
            return {"symbol":symbol,"note":"no_state"}

        side = st["side"]
        close_side = st["close_side"]
        entry = float(st["entry"])
        atr = float(st["atr"])
        filled = list(st.get("filled") or [False,False,False])

        stage = None
        if "_TP1_" in client_id: stage = 1
        elif "_TP2_" in client_id: stage = 2
        elif "_TP3_" in client_id: stage = 3
        if not stage:
            return {"symbol":symbol,"note":"not_grid_stage"}

        try:
            px_now = _fresh_mark(symbol) or entry
        except Exception:
            px_now = entry

        new_sl = None
        if stage == 1 and STREAM_TP_BE:
            new_sl = entry
        elif stage == 2:
            if side.upper() in ("LONG","BUY"):
                new_sl = entry + TP_LOCK_STAGE2_ATR*atr
            else:
                new_sl = entry - TP_LOCK_STAGE2_ATR*atr
        elif stage == 3:
            try:
                cancel_open_orders(symbol)
            except Exception:
                pass
            _del_state(symbol)
            try: tg_grid(f"{symbol} • TP3 hit → grid done (remaining orders cancelled)")
            except Exception: pass
            return {"symbol":symbol,"stage":stage,"action":"grid_done"}

        if new_sl is not None:
            new_sl = _align(symbol, float(new_sl), close_side)
            try:
                try:
                    for o2 in (get_open_orders(symbol) or []):
                        ty = str(o2.get("type","")).upper()
                        ro = bool(o2.get("reduceOnly") or (str(o2.get("reduceOnly","")).lower()=="true"))
                        if ro and ty in ("STOP","STOP_MARKET","STOP_LOSS","STOP_LOSS_LIMIT"):
                            cancel_order(symbol, o2.get("orderId"))
                except Exception:
                    try: cancel_open_orders(symbol)
                    except Exception: pass

                qty_total = float(st["qty_total"] or 0.0)
                place_stop_market(symbol, close_side, float(new_sl), float(qty_total), reduce_only=True)

                try:
                    if stage == 1 and STREAM_TP_BE:
                        tg_grid(f"{symbol} • TP1 hit → SL→BE @ {float(new_sl):.6f}")
                    elif stage == 2:
                        tg_grid(f"{symbol} • TP2 hit → lock profit • SL @ {float(new_sl):.6f}")
                except Exception:
                    pass
            except Exception as e:
                logger.warning({"event":"grid_sl_update_failed","symbol":symbol,"err":str(e)})

        if stage in (1,2,3):
            filled[stage-1] = True
            st["filled"] = filled
            st["last_touch"] = time.time()
            _save_state(symbol, st)

        return {"symbol":symbol,"stage":stage,"action":"sl_updated" if new_sl is not None else "stage_marked"}
    except Exception as e:
        logger.error({"event":"grid_stream_handler_failed","error":str(e)})
        return {"error": str(e)}

async def reconcile(symbol: str) -> Dict[str, Any]:
    symbol = symbol.upper().strip()
    st = _load_state(symbol)
    if not st:
        return {"ok": True, "note":"no_state"}

    has_pos=False
    try:
        for p in futures_position_risk() or []:
            if str(p.get("symbol")).upper()==symbol and abs(float(p.get("positionAmt") or 0.0))>0:
                has_pos=True; break
    except Exception:
        pass

    if not has_pos:
        try: cancel_open_orders(symbol)
        except Exception: pass
        _del_state(symbol)
        return {"ok": True, "note":"no_position_anymore_state_deleted"}

    oo = []
    try: oo = get_open_orders(symbol) or []
    except Exception: oo = []

    def _have(label: str)->bool:
        for o in oo:
            if str(o.get("clientOrderId","")).find(label)>=0:
                return True
        return False

    restored=[]
    try:
        side = st["side"]; close_side=st["close_side"]
        q1,q2,q3 = st["splits"]
        tp1,tp2,tp3 = st["targets"]
        if q1>0 and (not _have("_TP1_")):
            place_take_profit_market(symbol, close_side, float(tp1), float(q1), reduce_only=True, client_order_id=f"GRID_{symbol}_{side}_TP1_RO_{int(time.time())%1_000_000}")
            restored.append("TP1")
        if q2>0 and (not _have("_TP2_")):
            place_take_profit_market(symbol, close_side, float(tp2), float(q2), reduce_only=True, client_order_id=f"GRID_{symbol}_{side}_TP2_RO_{int(time.time())%1_000_000}")
            restored.append("TP2")
        if q3>0 and (not _have("_TP3_")):
            place_take_profit_market(symbol, close_side, float(tp3), float(q3), reduce_only=True, client_order_id=f"GRID_{symbol}_{side}_TP3_RO_{int(time.time())%1_000_000}")
            restored.append("TP3")
    except Exception as e:
        logger.warning({"event":"grid_restore_failed","symbol":symbol,"err":str(e)})

    return {"ok": True, "restored": restored}

async def cancel_grid(symbol: str) -> Dict[str, Any]:
    symbol = symbol.upper().strip()
    try:
        cancel_open_orders(symbol)
    except Exception as e:
        logger.warning({"event":"grid_cancel_orders_failed","symbol":symbol,"err":str(e)})
    _del_state(symbol)
    return {"ok": True}

async def ensure_grid_for(symbol: str) -> Dict[str, Any]:
    st = _load_state(symbol.upper())
    if st:
        return await reconcile(symbol)
    return await start_grid_for_position(symbol)




