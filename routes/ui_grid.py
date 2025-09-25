# routes/ui_grid.py
from __future__ import annotations
import logging, os, json
from collections import defaultdict
from typing import Dict, Any, List, Tuple

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

from utils.auth import require_api_key
from utils.trade_storage import load_trades  # שליפת טריידים קיימת

router = APIRouter(prefix="/ui/grid", tags=["UI-Grid"], dependencies=[Depends(require_api_key)])
logger = logging.getLogger("algogpt.routes.ui_grid")

# ---------- Helpers ----------
def _read_index_html() -> str:
    path = os.path.join("static", "ui", "index.html")
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def _inject_index(raw: str) -> str:
    """
    מזריק API token לדף סטטי בצד הלקוח.
    ה-frontend שולח Authorization/X-API-Key אוטומטית.
    """
    token = os.getenv("API_BEARER_TOKEN", "") or os.getenv("PRIMARY_API_TOKEN", "")
    base  = ""  # נשאר ריק כי אנו ניגשים לאותם נתיבים באותו host
    out = raw.replace("__API_TOKEN__", token)
    # אופציונלי: לקיבוע API_BASE אם תרצה לקרוא משירות אחר
    out = out.replace('window.API_BASE = "";', f'window.API_BASE = "{base}";')
    return out

def _list_accounts(trades: List[dict]) -> List[str]:
    accs = []
    seen = set()
    for t in trades:
        aid = t.get("account_id") or "default"
        if aid not in seen:
            seen.add(aid)
            accs.append(aid)
    return accs or ["default"]

def _active_grids(trades: List[dict], account_id: str | None = None) -> List[dict]:
    out = []
    for t in trades:
        if account_id and t.get("account_id") != account_id:
            continue
        # היגיון גנרי לגריד פעיל
        if t.get("is_grid") or t.get("strategy") == "grid":
            if (t.get("status") or "").upper() in ("OPEN", "ACTIVE", "RUNNING", ""):
                out.append({
                    "symbol": t.get("symbol"),
                    "orders": t.get("grid_orders") or t.get("orders") or [],
                    "trade_id": t.get("trade_id"),
                })
    return out

def _pnl_summary(trades: List[dict], account_id: str | None = None) -> Dict[str, Any]:
    total_realized = 0.0
    total_unrealized = 0.0
    by_symbol = defaultdict(lambda: {"realized":0.0,"unrealized":0.0})
    for t in trades:
        if account_id and t.get("account_id") != account_id:
            continue
        rp = float(t.get("realized_pnl") or 0)
        up = float(t.get("unrealized_pnl") or 0)
        sym = t.get("symbol") or "UNKNOWN"
        total_realized += rp
        total_unrealized += up
        by_symbol[sym]["realized"] += rp
        by_symbol[sym]["unrealized"] += up
    return {
        "total_realized": round(total_realized, 8),
        "total_unrealized": round(total_unrealized, 8),
        "by_symbol": {k: {"realized": round(v["realized"], 8), "unrealized": round(v["unrealized"], 8)} for k,v in by_symbol.items()},
    }

# ---------- UI HTML ----------
@router.get("/", response_class=HTMLResponse)
async def ui_grid_page(_: Request):
    try:
        raw = _read_index_html()
        html = _inject_index(raw)
        return HTMLResponse(html)
    except Exception as e:
        logger.exception("ui_grid_page_failed")
        return HTMLResponse(f"<h1>Error loading UI Grid: {e}</h1>", status_code=500)

# ---------- Data APIs (שה-frontend מצפה להם) ----------
@router.get("/accounts", response_class=JSONResponse)
async def ui_grid_accounts() -> Dict[str, Any]:
    try:
        trades: List[dict] = load_trades()
        return {"ok": True, "accounts": _list_accounts(trades)}
    except Exception as e:
        logger.exception("ui_grid_accounts_failed")
        return {"ok": False, "error": str(e), "accounts": []}

@router.get("/active", response_class=JSONResponse)
async def ui_grid_active(account_id: str | None = None) -> Dict[str, Any]:
    try:
        trades: List[dict] = load_trades()
        active = _active_grids(trades, account_id=account_id)
        return {"ok": True, "active": active}
    except Exception as e:
        logger.exception("ui_grid_active_failed")
        return {"ok": False, "error": str(e), "active": []}

@router.get("/trades", response_class=JSONResponse)
async def ui_grid_trades(account_id: str | None = None) -> Dict[str, Any]:
    try:
        trades: List[dict] = load_trades()
        if account_id:
            trades = [t for t in trades if t.get("account_id") == account_id]
        # ליישור שדות ש־frontend מצפה
        for t in trades:
            t.setdefault("tp_prices", t.get("take_profits") or [])
            t.setdefault("stop_price", t.get("sl") or t.get("stop_loss") or None)
        return {"ok": True, "trades": trades}
    except Exception as e:
        logger.exception("ui_grid_trades_failed")
        return {"ok": False, "error": str(e), "trades": []}

@router.get("/pnl", response_class=JSONResponse)
async def ui_grid_pnl(account_id: str | None = None) -> Dict[str, Any]:
    try:
        trades: List[dict] = load_trades()
        summary = _pnl_summary(trades, account_id=account_id)
        return {"ok": True, "summary": summary}
    except Exception as e:
        logger.exception("ui_grid_pnl_failed")
        return {"ok": False, "error": str(e), "summary": None}

# ---------- עזר לדיבוג ----------
@router.get("/_debug/token", response_class=PlainTextResponse)
async def ui_grid_token_echo() -> str:
    tok = os.getenv("API_BEARER_TOKEN","") or os.getenv("PRIMARY_API_TOKEN","")
    return tok or "(empty)"

