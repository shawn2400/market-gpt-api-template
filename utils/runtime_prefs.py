# utils/runtime_prefs.py
from __future__ import annotations
import threading

# מצב משתנה גלובלי (mute/unmute)
_runtime_prefs = {
    "mute": False
}
_lock = threading.Lock()

def is_muted() -> bool:
    """
    מחזיר אם המערכת במצב השתקה (mute).
    """
    with _lock:
        return _runtime_prefs.get("mute", False)

def set_mute(state: bool) -> None:
    """
    מעדכן מצב השתקה (mute/unmute).
    """
    with _lock:
        _runtime_prefs["mute"] = bool(state)

def toggle_mute() -> bool:
    """
    הופך את מצב ההשתקה (True -> False, False -> True).
    מחזיר את המצב החדש.
    """
    with _lock:
        new_state = not _runtime_prefs.get("mute", False)
        _runtime_prefs["mute"] = new_state
        return new_state

__all__ = [
    "is_muted",
    "set_mute",
    "toggle_mute",
]




