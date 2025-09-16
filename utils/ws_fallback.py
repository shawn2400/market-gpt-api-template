# -*- coding: utf-8 -*-
# utils/ws_fallback.py
from __future__ import annotations
import os, json, time, tempfile
from pathlib import Path
from typing import Optional, Dict, Any

# לא מיבאים binance_client.get_price כדי להימנע מתלות מעגלית.
# נשתמש ב־HTTP ישיר כ־fallback ל־mark/index price.
try:
    import httpx  # type: ignore
except Exception:
    httpx = None  # type: ignore

_WS_CACHE_PATH = Path(os.getenv("WS_CACHE_PATH", "static/cache/ws_prices.json"))
_FRESH_TTL = int(os.getenv("PRICE_WS_FRESH_TTL", "20"))
_HTTP_BASE = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com").rstrip("/")

def _read_cache() -> Dict[str, Any]:
    try:
        if not _WS_CACHE_PATH.exists():
            return {}
        return json.loads(_WS_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
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
        # כתיבה לא־אטומית (fallback)
        try:
            path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        except Exception:
            pass

def is_price_fresh(symbol: str, max_age_sec: int | None = None) -> bool:
    """בודק אם המחיר ב-WS cache טרי מספיק עבור הסימבול הנתון."""
    max_age = _FRESH_TTL if max_age_sec is None else int(max_age_sec)
    sym = symbol.upper()
    data = _read_cache()
    rec = data.get(sym)
    if not rec:
        return False
    try:
        ts = float(rec.get("ts") or 0.0)
    except Exception:
        return False
    return (time.time() - ts) <= max_age

def get_last_ts(symbol: str) -> float:
    """מחזיר חותמת הזמן (epoch seconds) של המחיר האחרון מה־WS cache, או 0.0 אם אין."""
    sym = symbol.upper()
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
    """מחזיר גיל המחיר בשניות, או None אם אין נתון."""
    ts = get_last_ts(symbol)
    if ts <= 0:
        return None
    return max(0.0, time.time() - ts)

def update_price(symbol: str, price: float, ts: Optional[float] = None) -> None:
    """מעדכן/שומר מחיר ב־WS cache (לשימוש פנימי או ע״י שכבות אחרות)."""
    try:
        sym = symbol.upper()
        data = _read_cache()
        data[sym] = {"price": float(price), "ts": float(ts or time.time())}
        _atomic_write_json(_WS_CACHE_PATH, data)
    except Exception:
        pass

def _http_mark_price(symbol: str) -> Optional[float]:
    """מביא mark/index price ב־HTTP ישיר (fallback עדין, ללא תלות בספריית הלקוח)."""
    if httpx is None:
        return None
    sym = symbol.upper()
    # ננסה premiumIndex (מכיל indexPrice ולעיתים markPrice). אם אין markPrice — נחזיר indexPrice.
    try:
        url = f"{_HTTP_BASE}/fapi/v1/premiumIndex"
        with httpx.Client(timeout=float(os.getenv("BINANCE_HTTP_TIMEOUT", "10.0"))) as cli:
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
    """
    מחזיר מחיר אחרון: קודם Cache מ-WS (אם טרי), אחרת HTTP mark/index. אם הכל נכשל — None.
    """
    sym = symbol.upper()
    data = _read_cache()
    rec = data.get(sym)
    if rec:
        try:
            px = float(rec.get("price") or 0.0)
            ts = float(rec.get("ts") or 0.0)
            if px > 0 and (time.time() - ts) <= _FRESH_TTL:
                return px
        except Exception:
            pass

    # Fallback ל-HTTP (mark/index)
    mp = _http_mark_price(sym)
    if mp and mp > 0:
        # נשמור בקאש כדי לשפר זרימה בפניות הבאות
        update_price(sym, mp)
        return mp

    return None

__all__ = ["is_price_fresh", "get_price", "get_last_ts", "get_price_age", "update_price"]
































