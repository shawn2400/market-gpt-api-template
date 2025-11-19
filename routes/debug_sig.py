from fastapi import APIRouter, Request, HTTPException, Header, Depends
import os, base64, hmac, hashlib
from utils.anti_replay import _canon, _sha256_hex, _b

router = APIRouter(prefix="/debug", tags=["Debug"], include_in_schema=False)

def _auth(authorization: str = Header("")):
    token = os.getenv("API_BEARER_TOKEN","")
    if not token or not authorization.startswith("Bearer "):
        raise HTTPException(401, "unauthorized")
    if not hmac.compare_digest(authorization.split(" ",1)[1], token):
        raise HTTPException(401, "unauthorized")
    if os.getenv("DEBUG_SIG","0") != "1":
        raise HTTPException(403, "debug_disabled")
    return True

@router.post("/sig")
async def sig_info(req: Request, _=Depends(_auth)):
    raw = await req.body()
    ts  = req.headers.get("X-Request-Timestamp") or ""
    nn  = req.headers.get("X-Request-Nonce") or ""
    route = req.query_params.get("route","/healthz")
    
    # Build canonical string (matching verify_request logic)
    nonce_canon = _canon(nn)
    route_canon = _canon(route)
    body_hash = hashlib.sha256(_b(raw)).hexdigest()
    canonical = f"{route_canon}|{ts}|{nonce_canon}|{body_hash}"
    
    return {
        "ok": True,
        "ts": ts,
        "nonce": nn,
        "route": route,
        "body_sha256": _sha256_hex(raw),
        "canon_b64": base64.b64encode(_b(canonical)).decode("utf-8"),
        "note": "No secret or expected signature is returned."
    }
