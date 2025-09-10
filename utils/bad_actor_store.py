# utils/bad_actor_store.py
from __future__ import annotations
import time, threading, json
from pathlib import Path
from typing import Optional, Dict, Any

_lock = threading.Lock()
_store: Dict[str, float] = {}  # key -> expire_ts (0 לשימור ללא TTL)
_path = Path("data/bad_actors.json")

def _now() -> float:
    return time.time()

def _cleanup() -> None:
    now = _now()
    dead = [k for k, exp in _store.items() if (exp > 0 and exp < now)]
    for k in dead:
        _store.pop(k, None)

def add(key: str, ttl_sec: Optional[int] = None) -> None:
    exp = 0.0
    if ttl_sec and ttl_sec > 0:
        exp = _now() + ttl_sec
    with _lock:
        _store[key] = exp
        _save()

def remove(key: str) -> None:
    with _lock:
        _store.pop(key, None)
        _save()

def is_bad(key: str) -> bool:
    with _lock:
        _cleanup()
        return key in _store

def all_keys() -> Dict[str, float]:
    with _lock:
        _cleanup()
        return dict(_store)

def _save() -> None:
    try:
        _path.parent.mkdir(parents=True, exist_ok=True)
        with _path.open("w", encoding="utf-8") as f:
            json.dump(_store, f)
    except Exception:
        pass

def load() -> None:
    try:
        if _path.exists():
            with _path.open("r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    with _lock:
                        _store.clear()
                        for k, exp in data.items():
                            try:
                                _store[str(k)] = float(exp)
                            except Exception:
                                _store[str(k)] = 0.0
    except Exception:
        pass

# טען בעת ייבוא המודול
load()
