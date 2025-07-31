import json
import os
from datetime import datetime

GRID_TRACKER_FILE = "grid_tracker.json"

def load_grids():
    """ טוען את מצב הגרידים מהקובץ (אם קיים) """
    if not os.path.exists(GRID_TRACKER_FILE):
        return []
    try:
        with open(GRID_TRACKER_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return []

def save_grids(grids):
    """ שומר את כל הגרידים לקובץ """
    try:
        with open(GRID_TRACKER_FILE, "w") as f:
            json.dump(grids, f, indent=2)
    except Exception as e:
        print(f"⚠️ שגיאה בשמירת grid_tracker: {e}")

def add_grid(grid_data):
    """ מוסיף גריד חדש לקובץ """
    grids = load_grids()
    grid_data["created_at"] = datetime.utcnow().isoformat()
    grids.append(grid_data)
    save_grids(grids)

def remove_grid(symbol):
    """ מסיר גריד לפי סימבול """
    grids = load_grids()
    grids = [g for g in grids if g.get("symbol") != symbol]
    save_grids(grids)

def get_open_grids():
    """ מחזיר את כל הגרידים הפתוחים """
    return load_grids()
