# server/routes/ui_grid.py
from __future__ import annotations
import os, time
from typing import Any, Dict, List, Optional
import httpx
from fastapi import APIRouter, Header, HTTPException

PRIMARY = os.getenv("PRIMARY_PUBLIC_HOST","").rstrip("/")
API_TOKEN = os.getenv("API_BEARER_TOKEN","")

router = APIRouter(prefix="/ui/grid", tags=["UI","Grid"])

def _auth_ok(x_api_key: Optional[str], authorization: Optional[str]) -> bool:
    tok = API_TOKEN.strip()
    if not tok: return True  # אם אין טוקן בסביבה – לא נכשיל (לשלב בדיקות)
    return (x_api_key == tok) or (authorization == f"Bearer {tok}")

async def _get_json(path: str, params: Dict[str, Any] | None = None) -> Dict[str, Any]:
    if not PRIMARY:
        return {}
    try:
        async with httpx.AsyncClient(timeout=10.0, trust_env=False) as cli:
            r = await cli.get(PRIMARY + path, params=params, headers={"Authorization": f"Bearer {API_TOKEN}"})
            r.raise_for_status()
            return r.json()
    except Exception:
        return {}

@router.get("/accounts")
async def accounts(
    x_api_key: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None),
):
    if not _auth_ok(x_api_key, authorization):
        raise HTTPException(status_code=401, detail="Unauthorized")
    # אם יש לך ריבוי חשבונות – החזר אותם כאן
    return {"ok": True, "accounts": ["main"]}

@router.get("/active")
async def active(
    account_id: Optional[str] = None,
    x_api_key: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None),
):
    if not _auth_ok(x_api_key, authorization):
        raise HTTPException(status_code=401, detail="Unauthorized")

    # דוגמה: נסה למשוך טריידים פתוחים מהראשי, והפוך ל-"גרידים פעילים"
    data = await _get_json("/executor/open-positions")
    items = data.get("items") or []
    active: List[Dict[str, Any]] = []
    for it in items:
        sym = it.get("symbol") or it.get("symbolPair") or it.get("symbol_code") or "UNKNOWN"
        active.append({"symbol": sym, "orders": it.get("orders") or []})
    return {"ok": True, "active": active}

@router.get("/trades")
async def trades(
    account_id: Optional[str] = None,
    x_api_key: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None),
):
    if not _auth_ok(x_api_key, authorization):
        raise HTTPException(status_code=401, detail="Unauthorized")

    # מקור 1: קובץ open_trades.json (אם קיים בראשי כ-API אחר, עדכן כאן)
    data = await _get_json("/grid/dashboard/data", params={"path":"open_trades.json"})
    items = data.get("items") or []
    out: List[Dict[str, Any]] = []
    for it in items:
        out.append({
            "trade_id": it.get("id") or it.get("trade_id") or it.get("oid") or str(int(time.time()*1000)),
            "symbol": it.get("symbol") or "UNKNOWN",
            "side": it.get("side") or it.get("direction") or "",
            "entry_price": it.get("entry_price") or it.get("entry") or it.get("base_price") or None,
            "stop_price": it.get("stop_price") or it.get("sl") or None,
            "tp_prices": it.get("tp_prices") or it.get("tp_levels") or [],
            "realized_pnl": it.get("realized_pnl") or 0.0,
        })
    return {"ok": True, "trades": out}

@router.get("/pnl")
async def pnl(
    account_id: Optional[str] = None,
    x_api_key: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None),
):
    if not _auth_ok(x_api_key, authorization):
        raise HTTPException(status_code=401, detail="Unauthorized")

    data = await _get_json("/pnl/summary")
    if not data:
        return {"ok": True, "summary": None}
    return {"ok": True, "summary": data.get("summary")}
