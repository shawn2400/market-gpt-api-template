# utils/storage.py
import os, uuid, json
from pathlib import Path
from utils.redis_client import redis_client

STATIC_DIR = Path("static/cache")
STATIC_DIR.mkdir(parents=True, exist_ok=True)


def save_payload(obj: dict, expire: int = 3600) -> str:
    """
    שומר JSON כבד בקובץ תחת static/cache.
    מחזיר נתיב יחסי להורדה (/static/cache/xxxx.json).
    """
    key = f"{uuid.uuid4().hex}.json"
    path = STATIC_DIR / key
    path.write_text(json.dumps(obj), encoding="utf-8")

    # Redis: שומר אינדקס -> path (כדי שיהיה קל לנקות/לנהל TTL)
    if redis_client:
        redis_client.setex(f"payload:{key}", expire, str(path))

    return f"/static/cache/{key}"


def cleanup_static(max_files: int = 500):
    """
    מנקה קבצים ישנים מה־cache אם חורג מ־max_files.
    """
    files = sorted(STATIC_DIR.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
    for f in files[max_files:]:
        try:
            f.unlink()
        except Exception:
            pass



