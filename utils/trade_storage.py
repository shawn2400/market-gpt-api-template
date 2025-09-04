# utils/trade_storage.py
import os, uuid, json
from pathlib import Path
from typing import Dict, Any, List
from utils.redis_client import redis_client

STATIC_DIR = Path("static/cache")
STATIC_DIR.mkdir(parents=True, exist_ok=True)

def save_payload(obj: dict, expire: int = 3600) -> str:
    key = f"{uuid.uuid4().hex}.json"
    path = STATIC_DIR / key
    path.write_text(json.dumps(obj), encoding="utf-8")
    if redis_client:
        redis_client.setex(f"payload:{key}", expire, str(path))
    return f"/static/cache/{key}"

def load_trades(path: str | Path | None = None) -> List[Dict[str, Any]]:
    try:
        if path is None:
            # 🔹 לטעון את כל הקבצים ב־static/cache
            files = sorted(STATIC_DIR.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
            trades: List[Dict[str, Any]] = []
            for f in files:
                try:
                    trades.extend(json.loads(f.read_text()))
                except Exception:
                    continue
            return trades
        else:
            p = Path(path)
            return json.loads(p.read_text())
    except Exception:
        return []

def cleanup_static(max_files: int = 500):
    files = sorted(STATIC_DIR.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
    for f in files[max_files:]:
        try:
            f.unlink()
        except Exception:
            pass




