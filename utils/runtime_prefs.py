# utils/runtime_prefs.py
from __future__ import annotations
from typing import Any, Dict, Optional, Set
import threading

_lock = threading.Lock()

# גלובלי + רשימת משתמשים מושתקים
_muted_global: bool = False
_muted_users: Set[str] = set()

_prefs: Dict[str, Any] = {}

def is_muted(chat_id: Optional[str] = None) -> bool:
    with _lock:
        if _muted_global:
            return True
        return str(chat_id) in _muted_users if chat_id else False

def mute(chat_id: Optional[str] = None) -> None:
    with _lock:
        global _muted_global
        if chat_id:
            _muted_users.add(str(chat_id))
        else:
            _muted_global = True

def clear_mute(chat_id: Optional[str] = None) -> None:
    with _lock:
        global _muted_global
        if chat_id:
            _muted_users.discard(str(chat_id))
        else:
            _muted_global = False
            _muted_users.clear()

# תאימות לאחור לשמות שהיו אצלך
def set_mute(state: bool) -> None:
    if state:
        mute(None)
    else:
        clear_mute(None)

def toggle_mute() -> bool:
    with _lock:
        if _muted_global:
            clear_mute(None)
        else:
            mute(None)
        return _muted_global

# העדפות כלליות
def get_pref(key: str, default: Any = None) -> Any:
    with _lock:
        return _prefs.get(key, default)

def set_pref(key: str, value: Any) -> None:
    with _lock:
        _prefs[key] = value

__all__ = [
    "is_muted",
    "mute",
    "clear_mute",
    "set_mute",
    "toggle_mute",
    "get_pref",
    "set_pref",
]





