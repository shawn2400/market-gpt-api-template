# utils/storage.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import os, json, uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

DATA_DIR = Path("data")
DATA_DIR.mkdir(parents=True, exist_ok=True)

STATIC_DIR = Path("static/cache")
STATIC_DIR.mkdir(parents=True, exist_ok=True)

# --- simple json storage ---
def save_json(name: str, obj: Any) -> str:
    p = DATA_DIR / (name if name.endswith(".json") else f"{name}.json")
    with p.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    return str(p)

def load_json(name: str, default: Optional[Any] = None) -> Any:
    p = DATA_DIR / (name if name.endswith(".json") else f"{name}.json")
    if not p.exists():
        return default
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)

# --- aliases for backward-compat ---
def put_json(name: str, obj: Any) -> bool:
    try:
        save_json(name, obj)
        return True
    except Exception:
        return False

def get_json(name: str) -> Optional[Any]:
    try:
        return load_json(name, None)
    except Exception:
        return None

# --- payload cache files (optionally mirrored to redis if available) ---
# soft optional redis
try:
    import redis  # type: ignore
except Exception:
    redis = None  # type: ignore

def _get_redis_client():
    url = (os.getenv("REDIS_URL") or "").strip()
    if not (redis and url):
        return None
    try:
        return redis.from_url(url, decode_responses=True)
    except Exception:
        return None

def save_payload(obj: Dict[str, Any], expire: int = 3600) -> str:
    key = f"{uuid.uuid4().hex}.json"
    path = STATIC_DIR / key
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    rc = _get_redis_client()
    if rc:
        try:
            rc.setex(f"payload:{key}", expire, json.dumps(obj, ensure_ascii=False))
        except Exception:
            pass
    return f"/static/cache/{key}"

def load_trades(path: Optional[str | Path] = None) -> List[Dict[str, Any]]:
    try:
        if path is None:
            files = sorted(STATIC_DIR.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
            trades: List[Dict[str, Any]] = []
            for f in files:
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                    if isinstance(data, list):
                        trades.extend([x for x in data if isinstance(x, dict)])
                    elif isinstance(data, dict):
                        trades.append(data)
                except Exception:
                    continue
            return trades
        else:
            p = Path(path)
            data = json.loads(p.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else [data]
    except Exception:
        return []

def cleanup_static(max_files: int = 500) -> None:
    files = sorted(STATIC_DIR.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
    for f in files[max_files:]:
        try:
            f.unlink()
        except Exception:
            continue

__all__ = [
    "save_json", "load_json", "put_json", "get_json",
    "save_payload", "load_trades", "cleanup_static",
]







