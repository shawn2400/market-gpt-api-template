# routes/rpc.py
from __future__ import annotations
from typing import Any, Dict, Optional, Tuple
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
import httpx

router = APIRouter(tags=["AI", "Market", "Price", "Trades", "Orders", "Executor", "Grid", "Indicators"])

class RPCRequest(BaseModel):
    target: str
    params: Dict[str, Any] = {}

class RPCResponse(BaseModel):
    ok: bool = True
    result: Dict[str, Any] = {}
    error: Optional[str] = None

# מיפוי יעדי RPC ל־endpoints קיימים בשרת
# הערה: price.get ינתב ל־/price/{symbol} (פרמטר symbol נדרש)
TARGETS: Dict[str, Tuple[str, str]] = {
    # AI
    "ai.ping":         ("GET",  "/ai/ping"),
    "ai.health":       ("GET",  "/ai/health"),
    "ai.price":        ("GET",  "/ai/price"),             # params: symbol
    "ai.analyze":      ("POST", "/ai/analyze"),            # json: {symbol, interval?}
    "ai.manual_scan":  ("GET",  "/ai/manual-scan"),        # params: symbols, interval

    # Price
    "price.get":       ("GET",  "/price/{symbol}"),        # params: symbol

    # Trades
    "trade.execute":   ("POST", "/trade/execute"),         # json: TradeRequest

    # Orders
    "orders.open":     ("GET",  "/orders/open"),
    "orders.history":  ("GET",  "/orders/history"),        # params: symbol?, limit?

    # Executor (קיימים בקוד שלך)
    "executor.status": ("GET",  "/executor/status"),
    "executor.health": ("GET",  "/executor/health"),       # params: symbol?
}

def _pop_symbol_path(path: str, params: Dict[str, Any]) -> str:
    """מחליף {symbol} בנתיב אם קיים, ושולף מה־params."""
    if "{symbol}" in path:
        sym = params.get("symbol")
        if not sym:
            raise HTTPException(status_code=400, detail="Missing required param: symbol")
        # הסרה מה־params כי הוא בנתיב
        params.pop("symbol", None)
        return path.replace("{symbol}", str(sym).upper())
    return path

@router.post("/rpc", response_model=RPCResponse, operation_id="postRPC", summary="Multiplexed RPC for all features")
async def post_rpc(req: RPCRequest, request: Request) -> RPCResponse:
    mapping = TARGETS.get(req.target)
    if not mapping:
        raise HTTPException(status_code=400, detail=f"Unknown target: {req.target}")

    method, raw_path = mapping
    # בונה URL בסיס על סמך הבקשה הנוכחית (כולל פרוטוקול/דומיין)
    base = str(request.base_url).rstrip("/")
    params = dict(req.params or {})
    path = _pop_symbol_path(raw_path, params)
    url = f"{base}{path}"

    # מעביר Authorization/X-API-Key קדימה אם קיימים
    headers: Dict[str, str] = {}
    auth = request.headers.get("authorization")
    if auth:
        headers["authorization"] = auth
    xkey = request.headers.get("x-api-key")
    if xkey:
        headers["x-api-key"] = xkey

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            if method == "GET":
                res = await client.get(url, params=params, headers=headers)
            else:
                res = await client.post(url, json=params, headers=headers)

        # אם לא 200 – מחזירים את פירוט השגיאה המקורית כדי לעזור בדיבוג
        if res.status_code != 200:
            try:
                detail = res.json()
            except Exception:
                detail = res.text
            raise HTTPException(status_code=res.status_code, detail=detail)

        # json תקין
        data = res.json()
        # אם התשובה כבר כוללת ok/result וכו' נחזיר כ־result “גולמי”
        return RPCResponse(ok=True, result=data)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))

