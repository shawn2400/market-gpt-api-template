from __future__ import annotations
import os
from fastapi import Header, HTTPException

# איסוף כל הטוקנים החוקיים
_tokens = set()
t1 = (os.getenv("API_BEARER_TOKEN") or "").strip()
if t1:
    _tokens.add(t1)
for t in (os.getenv("ALGOGPT_TOKENS") or "").split(","):
    t = t.strip()
    if t:
        _tokens.add(t)

SECURITY_ALLOW_ALL = (os.getenv("SECURITY_ALLOW_ALL", "0").strip().lower() in ("1", "true", "yes"))

async def require_api_key(
    authorization: str | None = Header(None),
    x_api_key: str | None = Header(None),
    token: str | None = None,  # מאפשר גם ?token=...
):
    if SECURITY_ALLOW_ALL:
        return True

    candidates: list[str] = []
    if authorization and authorization.lower().startswith("bearer "):
        candidates.append(authorization.split(" ", 1)[1].strip())
    if x_api_key:
        candidates.append(x_api_key.strip())
    if token:
        candidates.append(token.strip())

    for c in candidates:
        if c and c in _tokens:
            return True

    raise HTTPException(status_code=401, detail="Invalid API key")









































