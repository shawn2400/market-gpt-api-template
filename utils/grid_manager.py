import json
import os
from pathlib import Path
from typing import List, Dict, Any

# 📂 קובץ שבו נשמור את מצב הגרידים
CACHE_DIR = Path("static/cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)
GRIDS_FILE = CACHE_DIR / "grids.json"

# --- עוזרים פנימיים ---

def _load_grids() -> List[Dict[str, Any]]:
    """טוען את רשימת הגרידים מקובץ JSON"""
    if not GRIDS_FILE.exists():
        return []
    try:
        with open(GRIDS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def _save_grids(grids: List[Dict[str, Any]]) -> None:
    """שומר את רשימת הגרידים לקובץ JSON"""
    with open(GRIDS_FILE, "w", encoding="utf-8") as f:
        json.dump(grids, f, indent=2, ensure_ascii=False)

# --- API פנימי ---

def get_grid_status() -> List[Dict[str, Any]]:
    """מחזיר את כל הגרידים (פעילים ולא פעילים)"""
    return _load_grids()

def get_active_grids() -> List[Dict[str, Any]]:
    """מחזיר רק גרידים פעילים"""
    return [g for g in _load_grids() if g.get("active")]

def add_grid(grid: Dict[str, Any]) -> None:
    """מוסיף גריד חדש ושומר לקובץ"""
    grids = _load_grids()
    grids.append(grid)
    _save_grids(grids)

def stop_grid(grid_id: str) -> bool:
    """עוצר גריד לפי ID (משנה active=False)"""
    grids = _load_grids()
    updated = False
    for g in grids:
        if g.get("id") == grid_id:
            g["active"] = False
            updated = True
            break
    if updated:
        _save_grids(grids)
    return updated



