# utils/auth.py
import os
from typing import List, Optional

from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# HTTP Bearer (Authorization: Bearer <TOKEN>)
_security = HTTPBearer(auto_error=False)

def _allowed_tokens() -> List[str]:
    tokens: List[str] = []
    multi = os.getenv("API_TOKENS") or os.getenv("ALGOGPT_API_TOKENS")
    single = os.getenv("API_TOKEN") or os.getenv("ALGOGPT_API_TOKEN")
    if multi:
        tokens.extend([t.strip() for t in multi.split(",") if t.strip()])
    if single:
        tokens.append(single.strip())
    # הסר כפילויות וריקים
    return [t for i, t in enumerate(tokens) if t and t not in tokens[:i]]

def require_bearer_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_security),
) -> str:
    """
    תלות גלובלית לראוטים מוגנים.
    אפשר לבטל אימות זמנית ע״י DISABLE_AUTH=1.
    ניתן להגדיר טוקנים דרך:
      - API_TOKEN=<one>
      - API_TOKENS=<t1,t2,...>
    """
    if (os.getenv("DISABLE_AUTH", "").lower() in ("1", "true", "yes", "on")):
        return "auth-disabled"

    allowed = _allowed_tokens()
    if not allowed:
        # אין קונפיגורציית טוקן -> נחסום מפאת אבטחה
        raise HTTPException(status_code=401, detail="Auth not configured (set API_TOKEN or API_TOKENS).")

    if credentials is None or (credentials.scheme or "").lower() != "bearer":
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header.")

    token = credentials.credentials
    if token not in allowed:
        raise HTTPException(status_code=401, detail="Invalid token.")

    return token






