# routes/public_snapshot.py
from __future__ import annotations
import os, time, logging, json
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, validator, root_validator, conlist, confloat, constr
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from contextlib import suppress

log = logging.getLogger("algogpt.public_snapshot")
router = APIRouter(prefix="/public/snapshot", tags=["Public Feed"])

# ===== Bearer ACTION =====
_ACTION_TOKENS: List[str] = []
def _load_action_tokens() -> None:
    global _ACTION_TOKENS
    toks: List[str] = []
    for k in ("API_BEARER_TOKEN_ACTION", "API_BEARER_TOKEN", "PRIMARY_API_TOKEN"):
        t = (os.getenv(k, "") or "").strip()
        if t:
            toks.append(t)
    _ACTION_TOKENS = toks
_load_action_tokens()

def _require_action_bearer(req: Request) -> None:
    auth = req.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing_bearer")
    tok = auth.split(" ", 1)[1].strip()
    if not tok or tok not in _ACTION_TOKENS:
        raise HTTPException(status_code=401, detail="invalid_bearer")

# ===== Optional Redis (best-effort; no hard dependency) =====
_redis = None
with suppress(Exception):
    _rurl = os.getenv("REDIS_URL", "").strip()
    if _rurl:
        import redis.asyncio as aioredis  # type: ignore
        _redis = aioredis.from_url(_rurl, decode_responses=True)

REDIS_KEY = os.getenv("PUBLIC_SNAPSHOT_NS", "public:snapshot")
REDIS_TTL_SEC = int(os.getenv("PUBLIC_SNAPSHOT_TTL_SEC", "900") or 900)

# ===== In-memory fallback store (no files) =====
_SNAPSHOTS: Dict[str, Dict[str, Any]] = {}

# ===== Models & validation =====
Symbol = constr(regex=r'^[A-Z0-9_]{3,20}$')
Side   = constr(regex=r'^(LONG|SHORT)$')

class SL(BaseModel):
    stopPrice: confloat(gt=0) = Field(..., description="Stop price > 0")

class TP(BaseModel):
    price: confloat(gt=0) = Field(..., description="Take profit price > 0")
    split: confloat(gt=0, le=1) = Field(1.0, description="fraction 0<split<=1")

class SnapshotIn(BaseModel):
    symbol: Symbol
    side: Side
    score: Optional[confloat(ge=0, le=10)] = None
    entry: Optional[confloat(gt=0)] = None
    sl: Optional[SL] = None
    tp: Optional[conlist(TP, min_items=1, max_items=10)] = None
    note: Optional[constr(max_length=300)] = None

    @validator("symbol", pre=True)
    def _upcase(cls, v):
        return (v or "").strip().upper()

    @root_validator
    def _ensure_sl_tp(cls, vals):
        # לא מחייב SL/TP, אבל אם הגיעו—שיהיו הגיוניים ביחס ל־entry אם קיים
        entry = vals.get("entry")
        sl = vals.get("sl")
        tp = vals.get("tp") or []
        side = vals.get("side")

        if entry and sl:
            if side == "LONG" and sl.stopPrice >= entry:
                raise ValueError("SL must be below entry for LONG")
            if side == "SHORT" and sl.stopPrice <= entry:
                raise ValueError("SL must be above entry for SHORT")
        if entry and tp:
            for i, leg in enumerate(tp, start=1):
                if side == "LONG" and leg.price <= entry:
                    raise ValueError(f"TP{i} must be above entry for LONG")
                if side == "SHORT" and leg.price >= entry:
                    raise ValueError(f"TP{i} must be below entry for SHORT")
        return vals

class SnapshotOut(BaseModel):
    ok: bool
    stored: Dict[str, Any]

# ===== Helpers =====
async def _persist(symbol: str, payload: Dict[str, Any]) -> None:
    # Redis אם קיים, אחרת זיכרון. בלי כתיבה לקבצים.
    if _redis:
        try:
            key = f"{REDIS_KEY}:{symbol}"
            await _redis.set(key, json.dumps(payload, ensure_ascii=False), ex=REDIS_TTL_SEC)
            return
        except Exception as e:
            log.debug("public_snapshot.redis_failed: %s", e)
    _SNAPSHOTS[symbol] = payload

# ===== Routes =====
@router.post("/upsert", response_model=SnapshotOut, summary="Upsert public trade snapshot (ACTION Bearer)")
async def upsert_snapshot(body: SnapshotIn, request: Request):
    _require_action_bearer(request)

    now = int(time.time())
    payload = {
        "symbol": body.symbol,
        "side": body.side,
        "score": body.score,
        "entry": body.entry,
        "sl": (body.sl.dict() if body.sl else None),
        "tp": ([t.dict() for t in (body.tp or [])] or None),
        "note": body.note or "",
        "ts": now,
    }
    await _persist(body.symbol, payload)

    return SnapshotOut(ok=True, stored=payload)  # pydantic -> dict אוטומטי

# אופציונלי: GET קטן לבדיקה ידנית (ללא Bearer; קריאה בלבד)
@router.get("/inspect", summary="Inspect last snapshot (readonly)", response_model=Dict[str, Any])
async def inspect(symbol: Symbol):
    key = symbol.upper()
    if key in _SNAPSHOTS:
        return {"ok": True, "source": "memory", "data": _SNAPSHOTS[key]}
    if _redis:
        try:
            raw = await _redis.get(f"{REDIS_KEY}:{key}")
            if raw:
                return {"ok": True, "source": "redis", "data": json.loads(raw)}
        except Exception:
            pass
    raise HTTPException(status_code=404, detail="not_found")
