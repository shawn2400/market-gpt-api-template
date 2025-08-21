# utils/watchlist_utils.py
import os
import json
import logging
from typing import List, Dict, Any, Optional

WATCHLIST_PATH = os.getenv("WATCHLIST_PATH", "watchlist.json")
ANCHOR_SYMBOL = "BTCUSDT"

_DEFAULT_WATCHLIST: List[Dict[str, Any]] = [
    {"symbol": ANCHOR_SYMBOL, "direction": "LONG", "quality_score": 8},
    {"symbol": "ETHUSDT", "direction": "LONG", "quality_score": 7},
    {"symbol": "BNBUSDT", "direction": "LONG", "quality_score": 7},
]

logger = logging.getLogger("algogpt.watchlist")


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
        if direction is not None:
            direction = str(direction).strip().upper()
            if direction not in ("LONG", "SHORT"):
                direction = None
        q = it.get("quality_score", None)
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
    """
    ודא ש־BTCUSDT נמצא תמיד ברשימה.
    אם לא קיים – מוסיפים אותו עם quality=8.
    """
    if not any(it.get("symbol") == ANCHOR_SYMBOL for it in watchlist):
        watchlist.insert(0, {"symbol": ANCHOR_SYMBOL, "direction": "LONG", "quality_score": 8})
        logger.info({"event": "watchlist_anchor", "msg": f"{ANCHOR_SYMBOL} enforced"})
    return watchlist


def load_watchlist(min_quality: Optional[int] = None, path: str = WATCHLIST_PATH) -> List[Dict[str, Any]]:
    _ensure_file(path)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            raise ValueError("watchlist must be a list")
    except Exception as e:
        logger.error({"event": "watchlist_load_error", "error": str(e)})
        data = list(_DEFAULT_WATCHLIST)

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
            if isinstance(q, int) and q < int(min_quality):
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
            if not v:
                continue
            key = v["symbol"]
            if key in seen:
                continue
            seen.add(key)
            clean.append(v)

        clean = _ensure_anchor(clean)

        with open(path, "w", encoding="utf-8") as f:
            json.dump(clean, f, ensure_ascii=False, indent=2)
        logger.info({"event": "watchlist_save", "count": len(clean), "path": path})
        return True
    except Exception as e:
        logger.error({"event": "watchlist_save_error", "error": str(e)})
        return False
















