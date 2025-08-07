# utils/watchlist_utils.py
import json
import logging

def load_watchlist(min_quality: int = 6) -> list[dict]:
    """
    טוען את קובץ watchlist.json ומחזיר רק את הסמלים שעומדים בסף איכות מינימלי.
    """
    try:
        with open("watchlist.json", "r", encoding="utf-8") as f:
            data = json.load(f)
            filtered = [
                entry for entry in data
                if isinstance(entry, dict) and entry.get("quality_score", 0) >= min_quality
            ]
            logging.info(f"[watchlist] Loaded {len(filtered)} symbols with quality >= {min_quality}")
            return filtered
    except Exception as e:
        logging.warning(f"[watchlist] ⚠️ Error loading watchlist.json: {e} – returning empty list")
        return []











