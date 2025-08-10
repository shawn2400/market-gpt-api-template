# utils/watchlist_utils.py
import json
import logging
from typing import List, Dict, Any, Optional

WATCHLIST_FILE = "watchlist.json"

def load_watchlist(min_quality: int = 0) -> List[Dict[str, Any]]:
    """
    טוען את watchlist.json ומחזיר רשימת רשומות (dict) עם quality_score >= min_quality.
    מחזיר [] במקרה של שגיאה/קובץ חסר/פורמט לא תקין.
    """
    try:
        with open(WATCHLIST_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, list):
            logging.error(f"[watchlist] Invalid data format: expected list, got {type(data)}")
            return []

        filtered: List[Dict[str, Any]] = []
        for item in data:
            if not isinstance(item, dict):
                logging.warning(f"[watchlist] Skipping non-dict item: {item}")
                continue
            qs = item.get("quality_score", 0)
            try:
                qs = float(qs or 0)
            except Exception:
                qs = 0.0
            if qs >= float(min_quality):
                # נרמול סמלים
                sym = str(item.get("symbol", "")).strip().upper()
                if not sym:
                    logging.warning(f"[watchlist] Missing symbol in item: {item}")
                    continue
                out = dict(item)
                out["symbol"] = sym
                # דיפולט לכיוון
                dir_ = str(out.get("direction", out.get("main_direction", "LONG"))).strip().upper()
                out["direction"] = dir_ if dir_ in ("LONG", "SHORT") else "LONG"
                filtered.append(out)

        logging.info(f"[watchlist] Loaded {len(filtered)} symbols above quality {min_quality}")
        return filtered

    except FileNotFoundError:
        logging.error(f"[watchlist] File {WATCHLIST_FILE} not found")
    except json.JSONDecodeError as e:
        logging.error(f"[watchlist] JSON decode error: {e}")
    except Exception as e:
        logging.error(f"[watchlist] Unexpected error: {e}", exc_info=True)

    return []

def get_symbols_list(min_quality: int = 0) -> List[str]:
    """
    מחזיר רשימת סמלים (str) מתוך ה-watchlist לפי הסף.
    """
    wl = load_watchlist(min_quality=min_quality)
    symbols: List[str] = []
    for it in wl:
        if isinstance(it, dict) and it.get("symbol"):
            symbols.append(str(it["symbol"]).upper())
    # הסרת כפולים תוך שמירה על סדר
    seen = set()
    unique = []
    for s in symbols:
        if s not in seen:
            unique.append(s); seen.add(s)
    return unique













