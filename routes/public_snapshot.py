# routes/public_snapshot.py
from __future__ import annotations
import os, time, logging, json
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, validator, root_validator, conlist, confloat, constr
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from contextlib import suppress

log = logging.getLogger("algogpt.public_snapshot")
router = APIRouter(prefix="/public", tags=["Public Feed"])

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

# ===== helpers =====
async def _persist(symbol: str, payload: Dict[str, Any]) -> None:
    if _redis:
        try:
            key = f"{REDIS_KEY}:{symbol}"
            await _redis.set(key, json.dumps(payload, ensure_ascii=False), ex=REDIS_TTL_SEC)
            return
        except Exception as e:
            log.debug("public_snapshot.redis_failed: %s", e)
    _SNAPSHOTS[symbol] = payload

async def _load(symbol: str) -> Optional[Dict[str, Any]]:
    key = symbol.upper()
    if key in _SNAPSHOTS:
        return _SNAPSHOTS[key]
    if _redis:
        try:
            raw = await _redis.get(f"{REDIS_KEY}:{key}")
            if raw:
                return json.loads(raw)
        except Exception:
            pass
    return None

def _fmt_short_he(snap: Dict[str, Any]) -> str:
    sym = snap.get("symbol","—")
    side = {"LONG":"לונג 🟢","SHORT":"שורט 🔴"}.get(str(snap.get("side","")).upper(),"—")
    entry = snap.get("entry")
    sl = (snap.get("sl") or {}).get("stopPrice")
    tp = snap.get("tp") or []
    tp_txt = " | ".join([f"TP{i+1}:{t.get('price')}" for i,t in enumerate(tp[:3])]) if tp else "TP: —"
    return f"{sym} · {side} · כניסה {entry or '—'} · SL {sl or '—'} · {tp_txt}"

def _fmt_short_en(snap: Dict[str, Any]) -> str:
    sym = snap.get("symbol","—")
    side = {"LONG":"LONG 🟢","SHORT":"SHORT 🔴"}.get(str(snap.get("side","")).upper(),"—")
    entry = snap.get("entry")
    sl = (snap.get("sl") or {}).get("stopPrice")
    tp = snap.get("tp") or []
    tp_txt = " | ".join([f"TP{i+1}:{t.get('price')}" for i,t in enumerate(tp[:3])]) if tp else "TP: —"
    return f"{sym} · {side} · entry {entry or '—'} · SL {sl or '—'} · {tp_txt}"

# ===== routes =====
@router.post("/snapshot/upsert", summary="Upsert public trade snapshot (ACTION Bearer)")
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
    return {"ok": True, "stored": payload}

@router.get("/snapshot/inspect", summary="Inspect last snapshot (readonly)")
async def inspect(symbol: Symbol):
    data = await _load(symbol)
    if not data:
        raise HTTPException(status_code=404, detail="not_found")
    return {"ok": True, "data": data}

@router.get("/trade/status", summary="Human short trade status (he/en, readonly)")
async def trade_status(symbol: Optional[Symbol] = None, lang: Optional[str] = "he"):
    # אם לא הועבר symbol – קח אחרון מהזיכרון (אם קיים)
    data: Optional[Dict[str, Any]] = None
    if symbol:
        data = await _load(symbol)
    else:
        # קח אחרון לפי ts
        if _SNAPSHOTS:
            last = max(_SNAPSHOTS.values(), key=lambda d: d.get("ts", 0))
            data = last
        elif _redis:
            # אופציונלי: אם יש known set/list – דלג; כאן נשאר מינימלי
            data = None
    if not data:
        raise HTTPException(status_code=404, detail="no_snapshot")

    msg = _fmt_short_en(data) if str(lang).lower().startswith("en") else _fmt_short_he(data)
    return PlainTextResponse(msg, status_code=200, headers={"Cache-Control": "no-store"})

