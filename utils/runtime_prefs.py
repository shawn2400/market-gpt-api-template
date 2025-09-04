# utils/runtime_prefs.py
from __future__ import annotations
import threading

_lock = threading.Lock()
_prefs = {
    "mute": False,
}

def set_mute(value: bool) -> dict:
    """עדכון מצב השתקה (mute)"""
    with _lock:
        _prefs["mute"] = bool(value)
        return {"ok": True, "mute": _prefs["mute"]}

def get_prefs() -> dict:
    """מחזיר העדפות נוכחיות"""
    with _lock:
        return dict(_prefs)

__all__ = ["set_mute", "get_prefs"]





