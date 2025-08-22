# utils/grid_manager.py
from __future__ import annotations
import os, json, time
from pathlib import Path
from typing import List, Dict, Any, Optional
import threading

# 🔒 נעילה כדי למנוע קריאה/כתיבה מקבילה
_lock = threading.Lock()

CACHE_FILE = Path("static/cache/grids.json")
CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)

# ✅ טעינה מהדיסק
def _load() -> List[Dict[str, Any]]:
    if not CACHE_FILE.exists():
        return []
    try:
        with CACHE_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

# ✅ כתיבה לדיסק
def _save(data: List[Dict[str, Any]]) -> None:
    with CACHE_FILE.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# --- Public API ---

def get_grid_status() -> List[Dict[str, Any]]:
    """החזרת כל הגרידים מהקובץ"""
    with _lock:
        return _load()

def get_active_grids() -> List[Dict[str, Any]]:
    """החזרת גרידים פעילים בלבד"""
    with _lock:
        return [g for g in _load() if g.get("active")]

def add_grid(symbol: str, levels: int, allocated: float) -> Dict[str, Any]:
    """הוספת גריד חדש"""
    with _lock:
        grids = _load()
        new_grid = {
            "id": f"grid-{int(time.time())}",
            "symbol": symbol.upper(),
            "levels": levels,
            "allocated": float(allocated),
            "profit_pct": 0.0,
            "active": True,
            "ts": int(time.time())
        }
        grids.append(new_grid)
        _save(grids)
        return new_grid

def stop_grid(grid_id: str) -> Optional[Dict[str, Any]]:
    """עצירת גריד לפי מזהה"""
    with _lock:
        grids = _load()
        for g in grids:
            if g.get("id") == grid_id:
                g["active"] = False
                g["ts"] = int(time.time())
                _save(grids)
                return g
    return None

def update_profit(grid_id: str, profit_pct: float) -> Optional[Dict[str, Any]]:
    """עדכון רווח באחוזים לגריד קיים"""
    with _lock:
        grids = _load()
        for g in grids:
            if g.get("id") == grid_id:
                g["profit_pct"] = float(profit_pct)
                g["ts"] = int(time.time())
                _save(grids)
                return g
    return None


