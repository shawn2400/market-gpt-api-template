# utils/watchlist_utils.py
import json
import logging
from pathlib import Path
from typing import List, Optional, Union

_WATCHLIST_PATHS = [
    Path("./watchlist.json"),
    Path("./data/watchlist.json"),
]

def _load_json(path: Path) -> Optional[Union[list, dict]]:
    try:
        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logging.warning(f"[watchlist] failed reading {path}: {e}")
    return None

def load_watchlist(min_quality: Optional[float] = None) -> List[dict]:
    """
    טוען watchlist.json אם קיים. תומך בשתי סכמות:
      1) [{"symbol": "BTCUSDT", "quality": 7.2}, ...]
      2) ["BTCUSDT", "ETHUSDT", ...]
    מחזיר תמיד רשימת dict עם לפחות שדה symbol.
    """
    data = None
    for p in _WATCHLIST_PATHS:
        data = _load_json(p)
        if data is not None:
            break
    if data is None:
        return []

    items: List[dict] = []
    if isinstance(data, list):
        for row in data:
            if isinstance(row, dict) and row.get("symbol"):
                d = {"symbol": str(row["symbol"]).upper()}
                if "quality" in row:
                    try:
                        d["quality"] = float(row["quality"])
                    except Exception:
                        pass
                items.append(d)
            elif isinstance(row, str) and row.strip():
                items.append({"symbol": row.strip().upper()})
    else:
        logging.warning("[watchlist] unexpected json schema; expected list")
        return []

    if min_quality is not None:
        try:
            mq = float(min_quality)
            items = [x for x in items if float(x.get("quality", mq)) >= mq]
        except Exception:
            pass

    # ייחוד
    out, seen = [], set()
    for it in items:
        sym = it["symbol"].upper()
        if sym not in seen:
            seen.add(sym); out.append(it)
    return out

def get_symbols_list(min_quality: Optional[float] = None) -> List[str]:
    """
    מחזיר רשימת סימבולים מתוך ה-watchlist (אם קיים),
    מסנן לפי min_quality, ומחזיר ייחודי/UPPER.
    """
    items = load_watchlist(min_quality=min_quality) or []
    out, seen = [], set()
    for it in items:
        sym = str(it.get("symbol") or "").upper().strip()
        if sym and sym not in seen:
            seen.add(sym); out.append(sym)
    return out














