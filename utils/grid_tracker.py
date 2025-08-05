# utils/grid_tracker.py

import json
import os
import logging
from datetime import datetime

GRID_TRACKER_FILE = "grid_tracker.json"

def load_grids():
    """ טוען את מצב הגרידים מהקובץ (אם קיים) """
    if not os.path.exists(GRID_TRACKER_FILE):
        logging.info("📭 לא נמצא grid_tracker.json – יוצרת רשימה ריקה")
        return []
    try:
        with open(GRID_TRACKER_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        logging.warning("⚠️ grid_tracker.json אינו תקין (JSON לא חוקי) – מאפסים")
        return []
    except Exception as e:
        logging.error(f"❌ שגיאה בטעינת grid_tracker: {e}")
        return []

def save_grids(grids):
    """ שומר את כל הגרידים לקובץ """
    try:
        with open(GRID_TRACKER_FILE, "w", encoding="utf-8") as f:
            json.dump(grids, f, indent=2, ensure_ascii=False)
        logging.info(f"✅ נשמרו {len(grids)} גרידים ל־{GRID_TRACKER_FILE}")
    except Exception as e:
        logging.error(f"❌ שגיאה בשמירת grid_tracker: {e}")

def add_grid(grid_data):
    """ מוסיף גריד חדש לקובץ """
    grids = load_grids()
    grid_data["created_at"] = datetime.utcnow().isoformat()
    grids.append(grid_data)
    save_grids(grids)
    logging.info(f"➕ גריד חדש נוסף עבור {grid_data.get('symbol')}")

def remove_grid(symbol):
    """ מסיר גריד לפי סימבול """
    grids = load_grids()
    new_grids = [g for g in grids if g.get("symbol") != symbol]
    save_grids(new_grids)
    logging.info(f"🗑️ הוסר גריד עבור {symbol} (סה\"כ {len(grids) - len(new_grids)} גרידים)")

def get_open_grids():
    """ מחזיר את כל הגרידים הפתוחים """
    return load_grids()

