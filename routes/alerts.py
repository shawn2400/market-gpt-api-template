# /app/routes/alerts.py
from __future__ import annotations

import os, hmac, hashlib, time, re
from typing import Any, Dict
from fastapi import APIRouter, Body, HTTPException, Request

router = APIRouter(tags=["alerts"])

# COID builder
try:
    from utils.order_ids import build_client_order_id  # type: ignore
except Exception:
    _SAFE = re.compile(r'[^A-Za-z0-9._:/-]')
    def build_client_order_id(symbol: str, side: str, role: str = "ALERT") -> str:  # type: ignore
        pref = (os.getenv("ORDER_ID_PREFIX") or "ALG").strip() or "ALG"
        ts = int(time.time()*1000)
        raw = f"{pref}-{str(symbol).upper()}-{str(side).upper()}-{str(role).upper()}-{ts}"
        s = _SAFE.sub("_", raw)
        if len(s) <= 36: return s
        import hashlib
        h = hashlib.md5(s.encode("utf-8")).hexdigest()[:6]
        return f"{s[:36-(len(h)+1)]}_{h}"

def _sign_hex(secret_hex_or_text: str, payload: bytes) -> str:
    key = bytes.fromhex(secret_hex_or_text) if len(secret_hex_or_text)==64 else secret_hex_or_text.encode("utf-8")
    return hmac.new(key, payload, hashlib.sha256).hexdigest()

@router.post("/alerts/ingest", summary="Receive alert & place market order (simple)")
async def alerts_ingest(request: Request, payload: Dict[str, Any] = Body(...)):
    # אימות (אופציונלי)
    secret = (os.getenv("ALERTS_INGEST_HMAC_SECRET") or "").strip()
    if secret:
        want = _sign_hex(secret, await request.body())
        got  = request.headers.get("X-Signature") or ""
        if not hmac.compare_digest(got, want):
            raise HTTPException(status_code=401, detail="bad signature")

    symbol = (payload.get("symbol") or "").upper().strip()
    side   = (payload.get("side") or "").upper().strip()
    qty    = float(payload.get("qty") or payload.get("quantity") or 0)
    if not(symbol and side in ("BUY","SELL") and qty > 0):
        raise HTTPException(status_code=422, detail="bad params")

    try:
        from binance.client import Client  # type: ignore
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"binance import failed: {e}")

    api_key = (os.getenv("BINANCE_API_KEY") or "").strip()
    api_sec = (os.getenv("BINANCE_API_SECRET") or "").strip()
    if not (api_key and api_sec):
        raise HTTPException(status_code=500, detail="BINANCE keys missing")
    cli = Client(api_key, api_sec)

    coid = build_client_order_id(symbol, side, role="ALERT")

    try:
        order = cli.futures_create_order(
            symbol=symbol, side=side, type="MARKET",
            quantity=qty, newClientOrderId=coid
        )
        return {"ok": True, "order": {k: order.get(k) for k in ("orderId","clientOrderId","status","type","side")}}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"{e}")































