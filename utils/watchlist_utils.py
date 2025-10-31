# utils/watchlist_utils.py
from __future__ import annotations
import os, json, logging, random
from typing import List, Dict, Any, Optional, Tuple

# redis_client הוא אופציונלי; אם אין מחלקת Redis זמינה — נשתמש ב-None
try:
    from utils.redis_client import redis_client  # type: ignore
except Exception:
    redis_client = None  # type: ignore

WATCHLIST_PATH = os.getenv("WATCHLIST_PATH", "watchlist.json")
WATCHLIST_FALLBACK_PATH = os.getenv("WATCHLIST_FALLBACK_PATH", "watchlist_fallback.json")
ANCHOR_SYMBOL = "BTCUSDT"
REDIS_KEY = "algogpt:watchlist"

logger = logging.getLogger("algogpt.watchlist")

_DEFAULT_WATCHLIST: List[Dict[str, Any]] = [
    {"symbol": ANCHOR_SYMBOL, "direction": "LONG", "quality_score": 8},
    {"symbol": "ETHUSDT", "direction": "LONG", "quality_score": 7},
    {"symbol": "BNBUSDT", "direction": "LONG", "quality_score": 7},
]

def _top10_set_from_env() -> set[str]:
    s = os.getenv("TOP10_SYMBOLS", "")
    if s.strip():
        return set(x.strip().upper() for x in s.split(",") if x.strip())
    return {
        "BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT",
        "ADAUSDT","DOGEUSDT","TRXUSDT","TONUSDT","LTCUSDT"
    }

TOP10_SET = _top10_set_from_env()

def is_top10(symbol: str) -> bool:
    return symbol.upper() in TOP10_SET

def _ensure_file(path: str = WATCHLIST_PATH) -> None:
    if not os.path.exists(path):
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(_DEFAULT_WATCHLIST, f, ensure_ascii=False, indent=2)
            logger.info({"event": "watchlist_init", "msg": f"created default {path}"})
        except Exception as e:
            logger.error({"event": "watchlist_init_error", "error": str(e)})

def _validate_item(it: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    try:
        sym = str(it.get("symbol", "")).strip().upper()
        if not sym:
            return None
        direction = it.get("direction")
        if direction:
            direction = str(direction).strip().upper()
            if direction not in ("LONG", "SHORT"):
                direction = None
        q = it.get("quality_score")
        try:
            q = int(q) if q is not None else None
        except Exception:
            q = None
        out = {"symbol": sym}
        if direction: out["direction"] = direction
        if q is not None: out["quality_score"] = q
        if "weight" in it:
            try: out["weight"] = float(it["weight"])
            except Exception: pass
        if "notes" in it: out["notes"] = str(it["notes"])
        return out
    except Exception:
        return None

def _get_all_binance_futures_symbols() -> List[Dict[str, Any]]:
    """
    סורק דינמית את כל הסימבולים הזמינים ב-Binance Futures
    מחזיר רשימה במבנה: [{"symbol": "BTCUSDT", "quality_score": 7}, ...]
    """
    try:
        try:
            from utils.binance_client import _init_client
        except:
            from utils.binance_client import init_client as _init_client
        
        client = _init_client()
        if not client:
            logger.warning("Cannot get Binance client - dynamic scan disabled")
            return []
        
        # Get all Futures exchange info
        exchange_info = client.futures_exchange_info()
        
        # Filter active USDT perpetual contracts
        symbols_list = []
        for symbol_info in exchange_info.get("symbols", []):
            symbol = symbol_info.get("symbol", "")
            status = symbol_info.get("status", "")
            contract_type = symbol_info.get("contractType", "")
            quote_asset = symbol_info.get("quoteAsset", "")
            
            # Only USDT perpetuals that are TRADING
            if (quote_asset == "USDT" and 
                contract_type == "PERPETUAL" and 
                status == "TRADING"):
                
                # Assign quality score based on TOP10
                quality = 8 if symbol in TOP10_SET else 7
                
                symbols_list.append({
                    "symbol": symbol,
                    "quality_score": quality
                })
        
        logger.info({"event": "binance_futures_scan", "total_symbols": len(symbols_list)})
        return symbols_list
    
    except Exception as e:
        logger.error({"event": "binance_futures_scan_failed", "error": str(e)})
        return []

def _ensure_anchor(watchlist: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not any(it.get("symbol") == ANCHOR_SYMBOL for it in watchlist):
        watchlist.insert(0, {"symbol": ANCHOR_SYMBOL, "direction": "LONG", "quality_score": 8})
        logger.info({"event": "watchlist_anchor", "msg": f"{ANCHOR_SYMBOL} enforced"})
    return watchlist

def load_watchlist(min_quality: Optional[int] = None, path: str = WATCHLIST_PATH) -> List[Dict[str, Any]]:
    # Check if dynamic scan is enabled
    use_dynamic = os.getenv("USE_DYNAMIC_SCAN", "1").lower() in ("1", "true", "yes")
    
    if use_dynamic:
        # Scan all Binance Futures dynamically
        all_symbols = _get_all_binance_futures_symbols()
        
        if all_symbols:
            # Filter by minimum quality if specified
            if isinstance(min_quality, int):
                filtered = [s for s in all_symbols if s.get("quality_score", 0) >= min_quality]
            else:
                filtered = all_symbols
            
            # Ensure anchor and sort
            filtered = _ensure_anchor(filtered)
            filtered.sort(key=lambda d: (-(d.get("quality_score", -1)), d["symbol"]))
            
            logger.info({
                "event": "watchlist_load", 
                "src": "binance_dynamic_scan", 
                "total": len(all_symbols), 
                "after_filter": len(filtered)
            })
            return filtered
        
        # Fallback to file if dynamic scan fails
        logger.warning("Dynamic scan failed or returned no symbols, falling back to file watchlist")
    
    # Original file/redis logic
    data: Optional[List[Dict[str, Any]]] = None
    if redis_client:
        try:
            raw = redis_client.get(REDIS_KEY)
            if raw:
                data = json.loads(raw)
                logger.info({"event":"watchlist_load","src":"redis","count":len(data)})
        except Exception as e:
            logger.warning({"event":"watchlist_redis_error","error":str(e)})

    if not data:
        _ensure_file(path)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, list):
                raise ValueError("watchlist must be a list")
            logger.info({"event":"watchlist_load","src":"file","count":len(data)})
            if redis_client:
                try:
                    redis_client.set(REDIS_KEY, json.dumps(data), ex=3600)
                except Exception:
                    pass
        except Exception as e:
            logger.error({"event":"watchlist_load_error","error":str(e)})
            data = list(_DEFAULT_WATCHLIST)

    out: List[Dict[str, Any]] = []
    seen = set()
    for item in data:
        if not isinstance(item, dict): continue
        v = _validate_item(item)
        if not v: continue
        key = v["symbol"]
        if key in seen: continue
        if isinstance(min_quality, int) and key != ANCHOR_SYMBOL:
            q = v.get("quality_score")
            if isinstance(q, int) and q < min_quality:
                continue
        seen.add(key)
        out.append(v)

    out = _ensure_anchor(out)
    out.sort(key=lambda d: (-(d.get("quality_score", -1)), d["symbol"]))
    return out

def save_watchlist(items: List[Dict[str, Any]], path: str = WATCHLIST_PATH) -> bool:
    try:
        clean: List[Dict[str, Any]] = []
        seen = set()
        for it in items:
            v = _validate_item(it)
            if not v: continue
            key = v["symbol"]
            if key in seen: continue
            seen.add(key)
            clean.append(v)

        clean = _ensure_anchor(clean)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(clean, f, ensure_ascii=False, indent=2)

        if redis_client:
            try:
                redis_client.set(REDIS_KEY, json.dumps(clean), ex=3600)
                logger.info({"event":"watchlist_save","dst":"redis+file","count":len(clean)})
            except Exception:
                logger.info({"event":"watchlist_save","dst":"file","count":len(clean)})
        return True
    except Exception as e:
        logger.error({"event":"watchlist_save_error","error":str(e)})
        return False

def _safe_load_trades_log(path: str) -> List[Dict[str, Any]]:
    try:
        if not os.path.isfile(path): return []
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []

def compute_symbol_winrates(path: str = os.getenv("TRADES_LOG_PATH", "data/trades_log.json"),
                            limit: int = 400) -> Dict[str, float]:
    rows = _safe_load_trades_log(path)
    if not rows: return {}
    rows = rows[-limit:] if len(rows) > limit else rows
    stat: Dict[str, Tuple[int,int]] = {}
    for r in rows:
        sym = str(r.get("symbol","")).upper()
        if not sym: continue
        status = (r.get("status") or r.get("result",{}).get("status") or "").lower()
        pnl    = r.get("pnl") or r.get("result",{}).get("pnl")
        win = 1 if (status in {"win","success","closed_tp","tp"} or (isinstance(pnl,(int,float)) and pnl>0)) else 0
        w,t = stat.get(sym, (0,0))
        stat[sym] = (w+win, t+1)
    out: Dict[str,float] = {}
    for sym,(w,t) in stat.items():
        if t>0: out[sym] = w/float(t)
    return out

def _norm(x: float, lo: float, hi: float) -> float:
    if hi<=lo: return 0.0
    y = (x - lo) / (hi - lo)
    return max(0.0, min(1.0, y))

def build_symbol_pool(
    k: int = 12,
    min_quality: int = 6,
    include_anchor: bool = True,
    include_shorts: bool = True,
    balanced: bool = True,
    explore_prob: float = 0.2,
    winrate_weight: float = 0.5,
) -> List[str]:
    wl = load_watchlist(min_quality=min_quality)
    if not wl: return [ANCHOR_SYMBOL]

    wr = compute_symbol_winrates()
    qs_vals = [it.get("quality_score", 0) for it in wl if isinstance(it.get("quality_score"), int)]
    qs_lo, qs_hi = (min(qs_vals) if qs_vals else 0), (max(qs_vals) if qs_vals else 10)

    scored: List[Tuple[str,float]] = []
    for it in wl:
        sym = it["symbol"].upper()
        if not include_shorts and str(it.get("direction","")).upper()=="SHORT":
            continue
        qs = float(it.get("quality_score", 0))
        qs_norm = _norm(qs, qs_lo, max(qs_hi, qs_lo+1))
        wr_val  = wr.get(sym, 0.5)
        w = 0.5*qs_norm + winrate_weight*(wr_val-0.5) + 0.5
        if sym == ANCHOR_SYMBOL:
            w += 0.05
        scored.append((sym, w))

    scored.sort(key=lambda x: x[1], reverse=True)
    pool = [s for s,_ in scored[:max(k-1,1)]]
    tail = [s for s,_ in scored[max(k-1,1):]]
    import random as _rnd
    if tail and _rnd.random() < explore_prob:
        pool.append(_rnd.choice(tail))
    if include_anchor and ANCHOR_SYMBOL not in pool:
        pool.insert(0, ANCHOR_SYMBOL)
    seen=set(); out=[]
    for s in pool:
        if s in seen: continue
        seen.add(s); out.append(s)
    return out[:k]

def get_symbol_prefs(symbol: str) -> Dict[str, Any]:
    try:
        raw = os.getenv("SYMBOL_PREFS_JSON","").strip()
        if raw:
            mp = json.loads(raw)
            if isinstance(mp, dict):
                v = mp.get(symbol.upper())
                if isinstance(v, dict):
                    return v
    except Exception:
        pass
    if is_top10(symbol):
        return {"max_leverage": 15, "min_rr": 1.01, "budget_usd": 120.0, "modes": ["FUTURES","SPOT","GRID"]}
    return {"max_leverage": 10, "min_rr": 1.01, "budget_usd": 110.0, "modes": ["FUTURES","SPOT","GRID"]}

# ===== NEW: List[str] loader ל-auto_executor =====
def load_watchlist_env_or_fallback() -> List[str]:
    """
    1) אם WATCHLIST=BTCUSDT,ETHUSDT,... ב-ENV -> מחזיר מזה.
    2) אחרת טוען watchlist.json (עם מינימום איכות MIN_QUALITY_SCORE) ומפיק ממנו symbols.
    3) אם אין/שגוי -> fallback לקובץ WATCHLIST_FALLBACK_PATH (רשימת מחרוזות).
    4) מוסיף תמיד עוגן BTCUSDT אם לא קיים.
    """
    # ENV
    env_wl = [s.strip().upper() for s in (os.getenv("WATCHLIST","") or "").split(",") if s.strip()]
    if env_wl:
        if "BTCUSDT" not in env_wl:
            env_wl.insert(0, "BTCUSDT")
        # דה-דופ
        out: List[str] = []
        seen: set[str] = set()
        for s in env_wl:
            if s not in seen:
                out.append(s); seen.add(s)
        return out

    # JSON + min_quality
    try:
        qmin = int(float(os.getenv("MIN_QUALITY_SCORE", "0")))
    except Exception:
        qmin = None
    items = load_watchlist(min_quality=qmin)
    syms = [d["symbol"].upper() for d in items] if items else []

    if not syms:
        # Fallback לקובץ של רשימת מחרוזות
        try:
            with open(WATCHLIST_FALLBACK_PATH, "r", encoding="utf-8") as f:
                arr = json.load(f)
            syms = [str(x).strip().upper() for x in arr if str(x).strip()]
        except Exception:
            syms = [ANCHOR_SYMBOL, "ETHUSDT", "SOLUSDT"]

    if "BTCUSDT" not in syms:
        syms.insert(0, "BTCUSDT")
    # דה-דופ
    out: List[str] = []
    seen = set()
    for s in syms:
        if s not in seen:
            out.append(s); seen.add(s)
    return out

__all__ = [
    "WATCHLIST_PATH","WATCHLIST_FALLBACK_PATH","ANCHOR_SYMBOL",
    "load_watchlist","save_watchlist","build_symbol_pool","compute_symbol_winrates",
    "is_top10","get_symbol_prefs","load_watchlist_env_or_fallback",
]






















