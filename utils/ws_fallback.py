# utils/ws_fallback.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import os, json, time, tempfile
from pathlib import Path
from typing import Optional, Dict, Tuple, Any

try:
    import httpx  # optional
except Exception:
    httpx = None  # type: ignore

# in-memory cache the routers מצפים לו
# symbol -> (price, ts_ms)
LAST_PRICE_CACHE: Dict[str, Tuple[float, int]] = {}

_WS_CACHE_PATH = Path(os.getenv("WS_CACHE_PATH", "static/cache/ws_prices.json"))
_FRESH_TTL = int(os.getenv("PRICE_WS_FRESH_TTL", "20"))
_HTTP_BASE = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com").rstrip("/")

def _read_cache() -> Dict[str, Any]:
    try:
        if _WS_CACHE_PATH.exists():
            txt = _WS_CACHE_PATH.read_text(encoding="utf-8")
            return json.loads(txt) if txt else {}
    except Exception:
        pass
    return {}

def _atomic_write_json(path: Path, data: Dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", delete=False, dir=str(path.parent), encoding="utf-8") as tmp:
            json.dump(data, tmp, ensure_ascii=False, separators=(",", ":"))
            tmp.flush()
            os.fsync(tmp.fileno())
            tmp_name = tmp.name
        os.replace(tmp_name, path)
    except Exception:
        try:
            path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        except Exception:
            pass

def _now_ms() -> int:
    return int(time.time() * 1000)

def is_price_fresh(symbol: str, max_age_sec: int | None = None) -> bool:
    max_age = _FRESH_TTL if max_age_sec is None else int(max_age_sec)
    sym = symbol.upper()
    # prefer memory
    if sym in LAST_PRICE_CACHE:
        _, ts_ms = LAST_PRICE_CACHE[sym]
        if (time.time() - ts_ms / 1000.0) <= max_age:
            return True
    # fallback file
    data = _read_cache()
    rec = data.get(sym)
    if not rec:
        return False
    try:
        ts = float(rec.get("ts") or 0.0)
        return (time.time() - ts) <= max_age
    except Exception:
        return False

def get_last_ts(symbol: str) -> float:
    sym = symbol.upper()
    if sym in LAST_PRICE_CACHE:
        _, ts_ms = LAST_PRICE_CACHE[sym]
        return ts_ms / 1000.0
    data = _read_cache()
    rec = data.get(sym)
    if not rec:
        return 0.0
    try:
        ts = float(rec.get("ts") or 0.0)
        return ts if ts > 0 else 0.0
    except Exception:
        return 0.0

def get_price_age(symbol: str) -> Optional[float]:
    ts = get_last_ts(symbol)
    if ts <= 0:
        return None
    return max(0.0, time.time() - ts)

def update_price(symbol: str, price: float, ts: Optional[float] = None) -> None:
    sym = symbol.upper()
    ts_ms = int((ts or time.time()) * 1000)
    LAST_PRICE_CACHE[sym] = (float(price), ts_ms)
    # also persist to file
    try:
        data = _read_cache()
        data[sym] = {"price": float(price), "ts": float(ts or time.time())}
        _atomic_write_json(_WS_CACHE_PATH, data)
    except Exception:
        pass

def _http_mark_price(symbol: str) -> Optional[float]:
    if httpx is None:
        return None
    sym = symbol.upper()
    try:
        url = f"{_HTTP_BASE}/fapi/v1/premiumIndex"
        timeout = float(os.getenv("BINANCE_HTTP_TIMEOUT", "10.0"))
        with httpx.Client(timeout=timeout) as cli:
            r = cli.get(url, params={"symbol": sym})
            r.raise_for_status()
            data = r.json()
            if isinstance(data, list) and data:
                data = data[0]
            if isinstance(data, dict):
                mp = data.get("markPrice")
                ip = data.get("indexPrice")
                if mp is not None:
                    return float(mp)
                if ip is not None:
                    return float(ip)
    except Exception:
        return None
    return None

def get_price(symbol: str) -> Optional[float]:
    sym = symbol.upper()
    # memory first
    tup = LAST_PRICE_CACHE.get(sym)
    if tup:
        px, ts_ms = tup
        if px > 0 and (time.time() - ts_ms / 1000.0) <= _FRESH_TTL:
            return float(px)
    # file cache
    data = _read_cache()
    rec = data.get(sym)
    if rec:
        try:
            px = float(rec.get("price") or 0.0)
            ts = float(rec.get("ts") or 0.0)
            if px > 0 and (time.time() - ts) <= _FRESH_TTL:
                # warm memory
                update_price(sym, px, ts)
                return px
        except Exception:
            pass
    # HTTP fallback
    mp = _http_mark_price(sym)
    if mp and mp > 0:
        update_price(sym, mp)
        return mp
    return None

__all__ = ["LAST_PRICE_CACHE", "is_price_fresh", "get_price", "get_last_ts", "get_price_age", "update_price"]

































