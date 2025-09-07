# utils/runtime_prefs.py
from __future__ import annotations
import threading
from typing import Dict

# Thread-safe in-memory runtime preferences
_state: Dict[str, object] = {
    "mute": False,
}

_lock = threading.RLock()

def is_muted() -> bool:
    """Return whether notifications/execution are muted."""
    with _lock:
        return bool(_state.get("mute", False))

def set_mute(state: bool) -> None:
    """Set mute on/off."""
    with _lock:
        _state["mute"] = bool(state)

def toggle_mute() -> bool:
    """Toggle mute state and return the new value."""
    with _lock:
        new_state = not bool(_state.get("mute", False))
        _state["mute"] = new_state
        return new_state

# --- compat shim (נדרש ע"י routes.telegram_bot) ---
def clear_mute() -> None:
    """Alias for set_mute(False) for backward compatibility."""
    set_mute(False)

# אופציונלי: עוזר ל־/admin/debug להציג מצב נוכחי
def get_prefs_snapshot() -> Dict[str, object]:
    """Return a shallow copy of the current prefs (for debug/admin use)."""
    with _lock:
        return dict(_state)

__all__ = [
    "is_muted",
    "set_mute",
    "toggle_mute",
    "clear_mute",
    "get_prefs_snapshot",
]





