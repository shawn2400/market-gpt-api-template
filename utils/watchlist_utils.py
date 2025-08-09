import json
import logging

WATCHLIST_FILE = "watchlist.json"

def load_watchlist(min_quality: int = 0):
    try:
        with open(WATCHLIST_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            filtered = [item for item in data if item.get("quality_score", 0) >= min_quality]
            logging.info(f"[watchlist] Loaded {len(filtered)} symbols above quality {min_quality}")
            return filtered
    except Exception as e:
        logging.error(f"[watchlist] Failed to load watchlist: {e}")
        return []











