# routes/rpc.py
from __future__ import annotations
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Any, Dict, Optional
import httpx

router = APIRouter(tags=["AI", "Market", "Price", "Trades", "Orders", "Executor", "Grid", "Indicators"])

class RPCRequest(BaseModel):
    target: str
    params: Dict[str, Any] = {}

class RPCResponse(BaseModel):
    ok: bool = True
    result: Dict[str, Any] = {}
    error: Optional[str] = None

# מיפוי יעדים קיימים ל־endpoints שלך
TARGETS = {
    "ai.ping":         ("GET",  "/ai/ping"),
    "ai.health":       ("GET",  "/ai/health"),
    "ai.price":        ("GET",  "/ai/price"),          # דורש ?symbol=...
    "ai.analyze":      ("POST", "/ai/analyze"),         # body: {symbol, interval?}
    "ai.manual_scan":  ("GET",  "/ai/manual-scan"),     # דורש symbols & interval
    # הוסף כאן יעדים נוספים לפי הצורך...
}

@router.post("/rpc", response_model=RPCResponse, operation_id="postRPC", summary="Multiplexed RPC for all features")
async def post_rpc(req: RPCRequest, request: Request) -> RPCResponse:
    mapping = TARGETS.get(req.target)
    if not mapping:
        raise HTTPException(status_code=400, detail=f"Unknown target: {req.target}")

    method, path = mapping
    base = str(request.base_url).rstrip("/")
    url = f"{base}{path}"

    # מעבירים Authorization קדימה אם קיים
    headers = {}
    auth = request.headers.get("authorization")
    if auth:
        headers["authorization"] = auth

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            if method == "GET":
                r = await client.get(url, params=req.params or {}, headers=headers)
            else:
                r = await client.post(url, json=req.params or {}, headers=headers)

        if r.status_code != 200:
            # נחזיר את שגיאת המשנה לצורך דיבוג
            try:
                detail = r.json()
            except Exception:
                detail = r.text
            raise HTTPException(status_code=r.status_code, detail=detail)

        return RPCResponse(ok=True, result=r.json())
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
