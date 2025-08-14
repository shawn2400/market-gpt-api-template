# utils/watchlist_utils.py
import os
import json
import logging
from typing import List, Dict, Any, Optional

WATCHLIST_PATH = os.getenv("WATCHLIST_PATH", "watchlist.json")

_DEFAULT_WATCHLIST: List[Dict[str, Any]] = [
    {"symbol": "BTCUSDT", "direction": "LONG",  "quality_score": 8},
    {"symbol": "ETHUSDT", "direction": "LONG",  "quality_score": 7},
    {"symbol": "BNBUSDT", "direction": "LONG",  "quality_score": 7},
]

def _ensure_file(path: str = WATCHLIST_PATH) -> None:
    if not os.path.exists(path):
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(_DEFAULT_WATCHLIST, f, ensure_ascii=False, indent=2)
            logging.info(f"[watchlist] created default {path}")
        except Exception as e:
            logging.error(f"[watchlist] failed to create default {path}: {e}")

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

def load_watchlist(min_quality: Optional[int] = None, path: str = WATCHLIST_PATH) -> List[Dict[str, Any]]:
    _ensure_file(path)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            raise ValueError("watchlist must be a list")
    except Exception as e:
        logging.error(f"[watchlist] read failed ({e}); using default")
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
        if isinstance(min_quality, int):
            q = v.get("quality_score")
            if isinstance(q, int) and q < int(min_quality):
                continue
        seen.add(key); out.append(v)

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
        with open(path, "w", encoding="utf-8") as f:
            json.dump(clean, f, ensure_ascii=False, indent=2)
        logging.info(f"[watchlist] saved {len(clean)} items -> {path}")
        return True
    except Exception as e:
        logging.error(f"[watchlist] save failed: {e}")
        return False















