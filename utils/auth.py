import os
from fastapi import Header, HTTPException, status
from typing import Optional, Set

def _split_tokens(val: str) -> Set[str]:
    return {p.strip() for p in val.replace(";", ",").split(",") if p.strip()}

TOKENS: Set[str] = set()
for key in ("ALGOGPT_TOKENS", "ALGOGPT_TOKEN", "ALGOGPT_API_TOKEN", "API_BEARER", "API_BEARER_TOKEN"):
    v = (os.getenv(key) or "").strip()
    if not v:
        continue
    TOKENS |= _split_tokens(v)

ALLOW_ALL = os.getenv("SECURITY_ALLOW_ALL", "0").lower() in ("1", "true", "yes")

async def require_bearer_token(authorization: Optional[str] = Header(default=None)):
    if ALLOW_ALL:
        return True
    if not TOKENS:
        raise HTTPException(status_code=500, detail="Server missing API tokens")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid Authorization header")
    token = authorization.split(" ", 1)[1].strip()
    if token not in TOKENS:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return True



































