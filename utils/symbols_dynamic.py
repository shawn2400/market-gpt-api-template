# utils/symbols_dynamic.py
from __future__ import annotations
import os, time, json, logging
from typing import List, Dict, Any, Optional, Set

try:
    import httpx
except Exception as e:  # pragma: no cover
    raise RuntimeError(f"httpx is required: {e}")

# Redis – אופציונלי
try:
    from utils.redis_client import get_redis
except Exception:
    def get_redis(): return None  # type: ignore

BINANCE_FAPI = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com").rstrip("/")
LOG = logging.getLogger("algogpt.symbols_dynamic")

# ===== ENV knobs =====
# רשימת בסיס להכללה/החרגה (אם תרצה לקבע ידנית כמה סמלים)
INCLUDE_ENV = {s.strip().upper() for s in (os.getenv("SYMBOLS_INCLUDE", "") or "").split(",") if s.strip()}
EXCLUDE_ENV = {s.strip().upper() for s in (os.getenv("SYMBOLS_EXCLUDE", "") or "").split(",") if s.strip()}

# limit מרבי (0 = ללא הגבלה)
MAX_SYMBOLS = int(os.getenv("SYMBOLS_MAX", "0") or 0)

# סינון לפי נפח 24h (ב-USDT) — אם 0, לא מסננים
MIN_VOL24_USDT = float(os.getenv("SYMBOLS_MIN_VOL24_USDT", "0") or 0)

# קאש: TTL ב־Redis ובזיכרון
CACHE_TTL_SEC = int(os.getenv("SYMBOLS_CACHE_TTL_SEC", "900"))  # 15m
REDIS_KEY = "algogpt:futures_usdt_symbols"

_mem_cache: Dict[str, Any] = {"ts": 0.0, "symbols": []}


def _now() -> float:
    return time.time()


def _dedupe_keep_order(items: List[str]) -> List[str]:
    seen: Set[str] = set()
    out: List[str] = []
    for s in items:
        if s not in seen:
            out.append(s)
            seen.add(s)
    return out


def _filter_by_24h_volume(symbols: List[str], min_usdt: float) -> List[str]:
    """
    מסנן לפי 24hr tickers (quoteVolume ב-USDT). קורא endpoint מרובה.
    """
    if min_usdt <= 0 or not symbols:
        return symbols
    url = f"{BINANCE_FAPI}/fapi/v1/ticker/24hr"
    try:
        with httpx.Client(timeout=10.0) as cli:
            r = cli.get(url)
            r.raise_for_status()
            arr = r.json()
        vols: Dict[str, float] = {}
        for it in arr:
            try:
                sym = str(it.get("symbol") or "")
                qv = float(it.get("quoteVolume") or 0.0)
                vols[sym] = qv
            except Exception:
                continue
        keep = [s for s in symbols if vols.get(s, 0.0) >= min_usdt]
        return keep or symbols  # אם סינון ריק – נחזיר המקורי
    except Exception as e:
        LOG.warning({"event": "vol24_fetch_failed", "error": str(e)})
        return symbols


def _fetch_exchange_info_symbols() -> List[str]:
    """
    מחלץ רשימת USDT-Perp זמינים ופעילים מ-/fapi/v1/exchangeInfo.
    """
    url = f"{BINANCE_FAPI}/fapi/v1/exchangeInfo"
    with httpx.Client(timeout=12.0) as cli:
        r = cli.get(url)
        r.raise_for_status()
        info = r.json()
    symbols = []
    for s in info.get("symbols", []):
        try:
            if s.get("contractType") not in ("PERPETUAL", "CURRENT_QUARTER", "NEXT_QUARTER"):
                continue
            if str(s.get("status", "")).upper() != "TRADING":
                continue
            if str(s.get("quoteAsset", "")).upper() != "USDT":
                continue
            sym = str(s.get("symbol") or "").upper()
            if not sym.endswith("USDT"):
                continue
            symbols.append(sym)
        except Exception:
            continue
    return symbols


def _apply_env_overrides(symbols: List[str]) -> List[str]:
    if INCLUDE_ENV:
        # אם הגדרת INCLUDE — נשתמש אך ורק במה שב-INCLUDE (עם דה-דופ והחרגות)
        base = [s for s in _dedupe_keep_order(list(INCLUDE_ENV)) if s]
    else:
        base = list(symbols)

    if EXCLUDE_ENV:
        base = [s for s in base if s not in EXCLUDE_ENV]

    if MAX_SYMBOLS and MAX_SYMBOLS > 0:
        base = base[:MAX_SYMBOLS]

    return _dedupe_keep_order(base)


def _cache_set(symbols: List[str]) -> None:
    _mem_cache["ts"] = _now()
    _mem_cache["symbols"] = list(symbols)
    r = get_redis()
    if r:
        try:
            r.set(REDIS_KEY, json.dumps(symbols), ex=CACHE_TTL_SEC)
        except Exception:
            pass


def _cache_get() -> Optional[List[str]]:
    # memory
    if (_now() - float(_mem_cache.get("ts") or 0.0)) <= CACHE_TTL_SEC and _mem_cache.get("symbols"):
        return list(_mem_cache["symbols"])
    # redis
    r = get_redis()
    if r:
        try:
            raw = r.get(REDIS_KEY)
            if raw:
                arr = json.loads(raw)
                if isinstance(arr, list) and arr:
                    _mem_cache["ts"] = _now()
                    _mem_cache["symbols"] = list(arr)
                    return list(arr)
        except Exception:
            pass
    return None


def get_futures_usdt_symbols(*, with_liquidity: bool = True) -> List[str]:
    """
    רשימת סימבולים USDT-Perp דינמית, עם קאש פנימי ו-Redis.
    שימושי לסריקה רחבה.
    """
    cached = _cache_get()
    if cached:
        return list(cached)

    try:
        syms = _fetch_exchange_info_symbols()
        if with_liquidity and MIN_VOL24_USDT > 0:
            syms = _filter_by_24h_volume(syms, MIN_VOL24_USDT)
        syms = _apply_env_overrides(syms)
        # תמיד מכניסים BTCUSDT בתחילת הרשימה כעוגן
        if "BTCUSDT" not in syms:
            syms.insert(0, "BTCUSDT")
        syms = _dedupe_keep_order(syms)
        _cache_set(syms)
        LOG.info({"event": "symbols_dynamic.loaded", "count": len(syms), "min_vol24": MIN_VOL24_USDT})
        return syms
    except Exception as e:
        LOG.warning({"event": "symbols_dynamic.fallback", "error": str(e)})
        # Fallback מינימלי
        base = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]
        base = _apply_env_overrides(base)
        _cache_set(base)
        return base


__all__ = ["get_futures_usdt_symbols"]
