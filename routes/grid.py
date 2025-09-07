# routes/grid.py
from __future__ import annotations
import logging, json
from pathlib import Path
from typing import Dict, Any, Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from utils.auth import require_api_key
from utils.account_router import get_account_credentials
from utils.grid_utils import execute_grid_trade as basic_grid
from utils.grid_manager import start_grid_for_position
from utils.binance_spot_client import spot_price
from utils.binance_client import futures_mark_price

logger = logging.getLogger("algogpt.routes.grid")

router = APIRouter(prefix="/grid", tags=["Grid"], dependencies=[Depends(require_api_key)])

# ──────────────────────────────────────────────
# Models
# ──────────────────────────────────────────────
class GridTradeRequest(BaseModel):
    symbol: str = Field(..., example="BTCUSDT")
    side: str = Field(..., pattern="^(LONG|SHORT|BUY|SELL)$", example="LONG")
    budget: float = Field(..., gt=0, example=100)
    leverage: int = Field(10, ge=1, le=125, example=10)
    grids: int = Field(3, ge=1, le=20, example=3)
    dry_run: bool = Field(True, description="אם True → לא מציב פקודות אמיתיות")
    market: str = Field("futures", pattern="^(futures|spot)$", example="futures")
    account_id: str = Field("main", description="ID מה־accounts_config.json")

class GridTradeResponse(BaseModel):
    ok: bool
    mode: str
    symbol: str
    side: str
    market: str
    account_id: str
    base_price: Optional[float]
    budget: float
    leverage: Optional[int] = None
    levels: Optional[List[float]] = None
    allocations: Optional[List[float]] = None
    orders: Optional[Any] = None
    error: Optional[str] = None

# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────
_ALLOWED_DIRS = [Path("."), Path("storage"), Path("static"), Path("logs")]

def _safe_path(p: str) -> Path:
    p = (p or "").strip() or "trades_log.json"
    candidate = Path(p)
    if not candidate.is_absolute():
        for base in _ALLOWED_DIRS:
            test = (base / candidate).resolve()
            if test.exists():
                return test
        return (Path(".") / candidate).resolve()
    resolved = candidate.resolve()
    for base in _ALLOWED_DIRS:
        if str(resolved).startswith(str(base.resolve())):
            return resolved
    raise HTTPException(status_code=400, detail="Invalid path location")

def _load_json_or_empty(path: Path) -> Any:
    try:
        if not path.exists():
            return {"ok": True, "items": [], "note": f"file not found: {path.name}"}
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return {"ok": True, "items": data}
    except Exception as e:
        logger.exception("grid_dashboard_load_failed")
        raise HTTPException(status_code=500, detail=f"load failed: {e}")

# ──────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────
@router.get("/status")
def grid_status() -> Dict[str, Any]:
    return {"ok": True, "grid_enabled": True, "note": "Grid engine ready"}

@router.get("/active")
def grid_active() -> Dict[str, Any]:
    return {"ok": True, "active": []}

@router.get("/dashboard")
def grid_dashboard_info() -> Dict[str, Any]:
    return {
        "ok": True,
        "endpoints": {
            "data": "/grid/dashboard/data?path=trades_log.json",
            "active": "/grid/active",
            "status": "/grid/status",
        },
        "notes": "דשבורד לוגי; הדאטה נשלף דרך /grid/dashboard/data",
    }

@router.get("/dashboard/data")
def grid_dashboard_data(path: Optional[str] = Query(None, description="קובץ JSON לטעינה, ברירת מחדל trades_log.json")):
    safe = _safe_path(path or "trades_log.json")
    return _load_json_or_empty(safe)

@router.post("/trade", response_model=GridTradeResponse)
async def trade_grid(req: GridTradeRequest):
    sym = req.symbol.upper().strip()
    market = req.market.lower().strip()
    acc_id = req.account_id.strip()

    creds = get_account_credentials(acc_id)
    if not creds:
        raise HTTPException(status_code=400, detail=f"Account {acc_id} not found in accounts_config.json")

    try:
        if market == "spot":
            price = spot_price(sym)
            if not price:
                raise RuntimeError("Spot price unavailable")
            res = basic_grid(sym, levels=req.grids)
            return {
                "ok": bool(res.get("ok")),
                "mode": "spot_dry" if req.dry_run else "spot_live",
                "symbol": sym,
                "side": req.side,
                "market": "spot",
                "account_id": acc_id,
                "base_price": price,
                "budget": req.budget,
                "levels": res.get("grid_levels"),
                "allocations": None,
                "orders": [] if req.dry_run else None,
                "error": res.get("error"),
            }

        elif market == "futures":
            price = futures_mark_price(sym)
            if not price:
                raise RuntimeError("Futures mark price unavailable")

            if req.dry_run:
                res = basic_grid(sym, levels=req.grids)
                return {
                    "ok": bool(res.get("ok")),
                    "mode": "futures_dry",
                    "symbol": sym,
                    "side": req.side,
                    "market": "futures",
                    "account_id": acc_id,
                    "base_price": price,
                    "budget": req.budget,
                    "leverage": req.leverage,
                    "levels": res.get("grid_levels"),
                    "allocations": None,
                    "orders": [] if req.dry_run else None,
                    "error": res.get("error"),
                }
            else:
                res = await start_grid_for_position(sym, account_id=acc_id)
                return {
                    "ok": bool(res.get("ok")),
                    "mode": "futures_live",
                    "symbol": sym,
                    "side": req.side,
                    "market": "futures",
                    "account_id": acc_id,
                    "base_price": price,
                    "budget": req.budget,
                    "leverage": req.leverage,
                    "levels": None,
                    "allocations": None,
                    "orders": res,
                    "error": None if res.get("ok") else str(res.get("error")),
                }
        else:
            raise HTTPException(status_code=400, detail="Invalid market")

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("grid_trade_failed")
        raise HTTPException(status_code=500, detail=f"Grid trade failed: {e}")



















