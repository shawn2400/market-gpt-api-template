# routes/aliases.py
from __future__ import annotations
from fastapi import APIRouter, Query

router = APIRouter(tags=["aliases"])

# דוגמה פשוטה: יצירת מפה של כינויים -> סימבול
_ALIAS_MAP = {
    "btc": "BTCUSDT",
    "eth": "ETHUSDT",
    "sol": "SOLUSDT",
}

@router.get("/aliases/resolve")
def resolve_alias(a: str = Query(..., description="alias like 'btc'")):
    sym = _ALIAS_MAP.get(a.lower())
    return {"ok": bool(sym), "alias": a, "symbol": sym}
