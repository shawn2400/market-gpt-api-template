# utils/snapshot_store.py
from __future__ import annotations
import os, json, time, asyncio
from typing import Optional, Dict, Any
from contextlib import suppress

# Redis (אופציונלי)
_has_redis = False
_aioredis = None
_REDIS_URL = (os.getenv("REDIS_URL") or os.getenv("ALGOGPT_REDIS_URL") or "").strip()
if _REDIS_URL:
    with suppress(Exception):
        import redis.asyncio as aioredis  # type: ignore
        _aioredis = aioredis
        _has_redis = True

FILE_PATH = os.getenv("PUBLIC_SNAPSHOT_FILE", "/app/data/public_snapshots.json")
KEY_PREFIX = os.getenv("PUBLIC_SNAPSHOT_KEY_PREFIX", "public:snapshot:")
DEFAULT_TTL_SEC = int(os.getenv("PUBLIC_SNAPSHOT_TTL_SEC", "86400"))  # 24h (ללא מחיקה אקטיבית, רק מטא)

# ---- helpers ----
def _norm_symbol(symbol: str | None) -> Optional[str]:
    if not symbol:
        return None
    s = symbol.strip().upper()
    return s or None

async def _redis() -> Optional[Any]:
    if not _has_redis:
        return None
    try:
        r = _aioredis.from_url(_REDIS_URL, decode_responses=True)
        return r
    except Exception:
        return None

# ---- file store ----
def _file_load_all() -> Dict[str, Any]:
    try:
        if os.path.exists(FILE_PATH):
            with open(FILE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def _file_save_all(obj: Dict[str, Any]) -> None:
    try:
        os.makedirs(os.path.dirname(FILE_PATH), exist_ok=True)
        tmp = FILE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        os.replace(tmp, FILE_PATH)
    except Exception:
        pass

# ---- public API ----
async def upsert_snapshot(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    data: {symbol, side, score?, entry?, sl?, tp?, now?, pnl?, meta?}
    """
    sym = _norm_symbol(data.get("symbol"))
    if not sym:
        raise ValueError("missing symbol")

    snap = dict(data)
    snap["symbol"] = sym
    snap["ts"] = int(time.time())
    snap.setdefault("ttl_sec", DEFAULT_TTL_SEC)

    # Redis first
    r = await _redis()
    if r:
        key = KEY_PREFIX + sym
        try:
            await r.set(key, json.dumps(snap, ensure_ascii=False), ex=DEFAULT_TTL_SEC)
            return snap
        except Exception:
            pass

    # Fallback file
    all_snaps = _file_load_all()
    all_snaps[sym] = snap
    _file_save_all(all_snaps)
    return snap

async def get_snapshot(symbol: str) -> Optional[Dict[str, Any]]:
    sym = _norm_symbol(symbol)
    if not sym:
        return None

    r = await _redis()
    if r:
        key = KEY_PREFIX + sym
        try:
            v = await r.get(key)
            if v:
                return json.loads(v)
        except Exception:
            pass

    all_snaps = _file_load_all()
    snap = all_snaps.get(sym)
    return snap

async def list_symbols() -> list[str]:
    r = await _redis()
    if r:
        try:
            # ברוב ההתקנות אין KEYS/SCAN פרודקשני; לכן נשמור גם סט משני (אופציונלי).
            # אם אין סט, פשוט נחזיר [] ונשאיר ל-inspect לפי symbol.
            set_key = KEY_PREFIX + "_set"
            members = await r.smembers(set_key)
            return sorted([_norm_symbol(x) for x in members if _norm_symbol(x)] or [])
        except Exception:
            pass

    all_snaps = _file_load_all()
    return sorted(all_snaps.keys())

async def touch_symbol(symbol: str) -> None:
    """אופציונלי: לתחזוקת סט סמלים ב-Redis, אם רוצים list."""
    r = await _redis()
    if not r:
        return
    try:
        await r.sadd(KEY_PREFIX + "_set", _norm_symbol(symbol))
    except Exception:
        pass
