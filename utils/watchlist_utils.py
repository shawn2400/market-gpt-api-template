# utils/watchlist_utils.py
import os
import json
import logging
from typing import List, Dict, Any, Optional

from utils.redis_client import redis_client  # ✅ Redis client אם זמין

WATCHLIST_PATH = os.getenv("WATCHLIST_PATH", "watchlist.json")
ANCHOR_SYMBOL = "BTCUSDT"
REDIS_KEY = "algogpt:watchlist"

_DEFAULT_WATCHLIST: List[Dict[str, Any]] = [
    {"symbol": ANCHOR_SYMBOL, "direction": "LONG", "quality_score": 8},
    {"symbol": "ETHUSDT", "direction": "LONG", "quality_score": 7},
    {"symbol": "BNBUSDT", "direction": "LONG", "quality_score": 7},
]

logger = logging.getLogger("algogpt.watchlist")

# -------------------- Helpers --------------------
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
        if direction:
            out["direction"] = direction
        if q is not None:
            out["quality_score"] = q
        if "weight" in it:
            try:
                out["weight"] = float(it["weight"])
            except Exception:
                pass
        if "notes" in it:
            out["notes"] = str(it["notes"])
        return out
    except Exception:
        return None

def _ensure_anchor(watchlist: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not any(it.get("symbol") == ANCHOR_SYMBOL for it in watchlist):
        watchlist.insert(0, {"symbol": ANCHOR_SYMBOL, "direction": "LONG", "quality_score": 8})
        logger.info({"event": "watchlist_anchor", "msg": f"{ANCHOR_SYMBOL} enforced"})
    return watchlist

# -------------------- Load --------------------
def load_watchlist(min_quality: Optional[int] = None, path: str = WATCHLIST_PATH) -> List[Dict[str, Any]]:
    data: Optional[List[Dict[str, Any]]] = None

    # 🔹 קודם ננסה להביא מ־Redis
    if redis_client:
        try:
            raw = redis_client.get(REDIS_KEY)
            if raw:
                data = json.loads(raw)
                logger.info({"event": "watchlist_load", "src": "redis", "count": len(data)})
            else:
                raise ValueError("redis empty")
        except Exception as e:
            logger.warning({"event": "watchlist_redis_fallback", "error": str(e)})

    # 🔹 אם אין Redis או אין נתונים → טען מהקובץ
    if data is None:
        _ensure_file(path)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, list):
                raise ValueError("watchlist must be a list")
            logger.info({"event": "watchlist_load", "src": "file", "count": len(data)})

            # ✅ שמירה ל־Redis אחרי טעינה מהקובץ
            if redis_client:
                try:
                    redis_client.set(REDIS_KEY, json.dumps(data), ex=3600)
                    logger.info({"event": "watchlist_sync", "dst": "redis", "count": len(data)})
                except Exception as e:
                    logger.error({"event": "watchlist_sync_error", "error": str(e)})
        except Exception as e:
            logger.error({"event": "watchlist_load_error", "error": str(e)})
            data = list(_DEFAULT_WATCHLIST)

    # 🔹 Validate + Filter
    out: List[Dict[str, Any]] = []
    seen = set()
    for item in data:
        if not isinstance(item, dict):
            continue
        v = _validate_item(item)
        if not v:
            continue
        key = v["symbol"]
        if key in seen:
            continue
        if isinstance(min_quality, int) and key != ANCHOR_SYMBOL:
            q = v.get("quality_score")
            if isinstance(q, int) and q < min_quality:
                continue
        seen.add(key)
        out.append(v)

    out = _ensure_anchor(out)
    out.sort(key=lambda d: (-(d.get("quality_score", -1)), d["symbol"]))
    return out

# -------------------- Save --------------------
def save_watchlist(items: List[Dict[str, Any]], path: str = WATCHLIST_PATH) -> bool:
    try:
        clean: List[Dict[str, Any]] = []
        seen = set()
        for it in items:
            v = _validate_item(it)
            if not v:
                continue
            key = v["symbol"]
            if key in seen:
                continue
            seen.add(key)
            clean.append(v)

        clean = _ensure_anchor(clean)

        # 🔹 כתיבה ל־קובץ
        with open(path, "w", encoding="utf-8") as f:
            json.dump(clean, f, ensure_ascii=False, indent=2)

        # 🔹 כתיבה ל־Redis
        if redis_client:
            try:
                redis_client.set(REDIS_KEY, json.dumps(clean), ex=3600)
                logger.info({"event": "watchlist_save", "dst": "redis+file", "count": len(clean)})
            except Exception as e:
                logger.error({"event": "watchlist_save_redis_error", "error": str(e)})
        else:
            logger.info({"event": "watchlist_save", "dst": "file", "count": len(clean)})

        return True
    except Exception as e:
        logger.error({"event": "watchlist_save_error", "error": str(e)})
        return False

















