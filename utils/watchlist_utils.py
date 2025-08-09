# utils/watchlist_utils.py

import json
import logging

WATCHLIST_FILE = "watchlist.json"

def load_watchlist(min_quality: int = 0):
    """
    טוען את קובץ watchlist.json ומחזיר רשימה של סמלים עם ציון איכות מעל min_quality.
    מחזיר רשימה ריקה במקרה של שגיאה.
    """
    try:
        with open(WATCHLIST_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

            if not isinstance(data, list):
                logging.error(f"[watchlist] Invalid data format: expected list, got {type(data)}")
                return []

            filtered = [item for item in data if isinstance(item, dict) and item.get("quality_score", 0) >= min_quality]

            logging.info(f"[watchlist] Loaded {len(filtered)} symbols above quality {min_quality}")
            return filtered
    except FileNotFoundError:
        logging.error(f"[watchlist] File {WATCHLIST_FILE} not found")
    except json.JSONDecodeError as e:
        logging.error(f"[watchlist] JSON decode error: {e}")
    except Exception as e:
        logging.error(f"[watchlist] Unexpected error: {e}")

    return []











