# server_routes.py
from __future__ import annotations
import os
from fastapi import FastAPI, HTTPException, Depends, Query, Header
from pydantic import BaseModel
from server_signing import verify_signature

app = FastAPI()

# -------- Optional Bearer auth --------
REQUIRE_BEARER = (os.getenv("REQUIRE_BEARER", "0").lower() in {"1", "true", "yes", "on"})
API_BEARER_TOKEN = os.getenv("API_BEARER_TOKEN", "")  # set to enable enforcement

def require_bearer(authorization: str | None = Header(default=None)) -> bool:
    if not REQUIRE_BEARER:
        return True
    if not API_BEARER_TOKEN:
        raise HTTPException(status_code=500, detail="Bearer required but API_BEARER_TOKEN not set")
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    token = authorization.split(" ", 1)[1].strip()
    if token != API_BEARER_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid bearer token")
    return True

# -------- Models --------
class ApproveResponse(BaseModel):
    ok: bool
    ticket_id: str
    detail: str | None = None

class HealthResponse(BaseModel):
    ok: bool
    require_bearer: bool

# -------- Routes --------
@app.get("/health", response_model=HealthResponse)
def health():
    return HealthResponse(ok=True, require_bearer=REQUIRE_BEARER)

@app.get("/ops/approve/signed", response_model=ApproveResponse)
def approve_signed(
    ticket_id: str = Query(..., description="Ticket id"),
    exp: str = Query(..., description="Expiry (unix seconds or ms)"),
    sig: str = Query(..., description="HMAC-SHA256 signature (hex or b64url)"),
    _auth_ok: bool = Depends(require_bearer),
):
    ok, why = verify_signature(ticket_id, exp, sig)
    if not ok:
        # Return 401 for signature failures to match your logs
        raise HTTPException(status_code=401, detail=f"Bad signature: {why}")

    # TODO: perform the actual approval/side-effects here (db/redis/exchange/etc.)
    # Make sure to validate the ticket state (not already approved/rejected/expired).
    return ApproveResponse(ok=True, ticket_id=ticket_id, detail="approved")
