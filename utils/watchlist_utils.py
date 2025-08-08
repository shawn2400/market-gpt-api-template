# utils/watchlist_utils.py
import json
import os
import logging
from typing import List

WATCHLIST_FILE = "watchlist.json"

def load_watchlist(min_quality: int = 6) -> List[str]:
    """
    טוען את רשימת המעקב מהקובץ המקומי.
    מחזיר רשימת סמלים בלבד, מסוננים לפי ציון איכות.
    אם הקובץ לא קיים או ריק – מחזיר רשימה ריקה.
    """
    if not os.path.exists(WATCHLIST_FILE):
        logging.warning(f"[watchlist] קובץ {WATCHLIST_FILE} לא נמצא")
        return []

    try:
        with open(WATCHLIST_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, list):
            logging.error(f"[watchlist] פורמט קובץ {WATCHLIST_FILE} אינו תקין")
            return []

        filtered = [item["symbol"] for item in data
                    if isinstance(item, dict) and
                       item.get("quality_score", 0) >= min_quality]

        logging.info(f"[watchlist] נטענו {len(filtered)} סמלים מעל quality {min_quality}")
        return filtered

    except Exception as e:
        logging.error(f"[watchlist] שגיאה בטעינת {WATCHLIST_FILE}: {e}")
        return []











