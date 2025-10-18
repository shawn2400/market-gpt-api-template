# routes/public_snapshot.py
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from .auth import require_bearer_action  # מחייב ACTION bearer

router = APIRouter(prefix="/public/snapshot", tags=["Public Feed"])

class Leg(BaseModel):
    price: float
    split: float | None = None

class Snapshot(BaseModel):
    symbol: str
    side: str
    score: float | None = None
    sl: dict | None = None
    tp: list[Leg] | None = None

@router.post("/upsert")
def upsert_snapshot(s: Snapshot, _=Depends(require_bearer_action)):
    # TODO: כתיבה ל־store שלך (זיכרון/Redis/SQLite) — או לחלץ לפונקציה קיימת
    ok = True
    if not ok:
        raise HTTPException(500, "failed to upsert snapshot")
    return {"ok": True}
