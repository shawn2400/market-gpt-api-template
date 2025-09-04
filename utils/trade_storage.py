# utils/trade_storage.py
import os, uuid, json
from pathlib import Path
from typing import Dict, Any, List, Optional
from utils.redis_client import redis_client

STATIC_DIR = Path("static/cache")
STATIC_DIR.mkdir(parents=True, exist_ok=True)

def save_payload(obj: dict, expire: int = 3600) -> str:
    """שומר payload לקובץ JSON + Redis (אם קיים)."""
    key = f"{uuid.uuid4().hex}.json"
    path = STATIC_DIR / key
    path.write_text(json.dumps(obj), encoding="utf-8")
    if redis_client:
        try:
            redis_client.setex(f"payload:{key}", expire, str(path))
        except Exception:
            pass
    return f"/static/cache/{key}"

def load_trades(path: Optional[str | Path] = None) -> List[Dict[str, Any]]:
    """טוען טריידים מה־cache. אם path=None → קורא את כל הקבצים בתיקייה."""
    try:
        if path is None:
            files = sorted(STATIC_DIR.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
            trades: List[Dict[str, Any]] = []
            for f in files:
                try:
                    data = json.loads(f.read_text())
                    if isinstance(data, list):
                        trades.extend(data)
                    elif isinstance(data, dict):
                        trades.append(data)
                except Exception:
                    continue
            return trades
        else:
            p = Path(path)
            data = json.loads(p.read_text())
            return data if isinstance(data, list) else [data]
    except Exception:
        return []

def cleanup_static(max_files: int = 500):
    """מוחק קבצי cache ישנים ושומר על מספר מקסימלי."""
    files = sorted(STATIC_DIR.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
    for f in files[max_files:]:
        try:
            f.unlink()
        except Exception:
            continue





