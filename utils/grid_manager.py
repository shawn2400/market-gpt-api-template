# utils/grid_manager.py
import json
from pathlib import Path
from typing import List, Dict, Any

# קובץ אחסון לגרידים
GRID_FILE = Path("static/cache/grids.json")
GRID_FILE.parent.mkdir(parents=True, exist_ok=True)

# ✅ טען גרידים מהקובץ
def _load_grids() -> List[Dict[str, Any]]:
    if GRID_FILE.exists():
        try:
            with open(GRID_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

# ✅ שמור גרידים לקובץ
def _save_grids(grids: List[Dict[str, Any]]) -> None:
    with open(GRID_FILE, "w", encoding="utf-8") as f:
        json.dump(grids, f, ensure_ascii=False, indent=2)

# --- API פנימיים ---

def get_grid_status() -> List[Dict[str, Any]]:
    """מחזיר את כל הגרידים (מהקובץ)"""
    return _load_grids()

def get_active_grids() -> List[Dict[str, Any]]:
    """מחזיר רק את הגרידים האקטיביים"""
    return [g for g in _load_grids() if g.get("active")]

def add_grid(grid: Dict[str, Any]) -> None:
    """הוסף גריד חדש"""
    grids = _load_grids()
    grids.append(grid)
    _save_grids(grids)

def stop_grid(grid_id: str) -> bool:
    """עצור גריד לפי ID"""
    grids = _load_grids()
    updated = False
    for g in grids:
        if g.get("id") == grid_id:
            g["active"] = False
            updated = True
    if updated:
        _save_grids(grids)
    return updated

