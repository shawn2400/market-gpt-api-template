# utils/auth.py
from __future__ import annotations

import os
import hmac
from typing import Set, Optional
from fastapi import Header, HTTPException, status, Request

# ──────────────────────────────────────────────────────────────────────────────
# ENV → אגרגציית טוקנים (תומך יחיד/מרובה מופרד בפסיקים/נקודה-פסיק)
# נתמכים: API_BEARER_TOKEN, API_BEARER_TOKEN_ALT, API_BEARER_TOKENS,
#          ALGOGPT_TOKEN, ALGOGPT_TOKENS, API_BEARER
# ──────────────────────────────────────────────────────────────────────────────
def _split_tokens(val: str) -> Set[str]:
    raw = val.replace(";", ",").split(",")
    return {p.strip() for p in raw if p and p.strip()}

def _load_tokens_from_env() -> Set[str]:
    keys = (
        "API_BEARER_TOKEN",
        "API_BEARER_TOKEN_ALT",
        "API_BEARER_TOKENS",
        "ALGOGPT_TOKEN",
        "ALGOGPT_TOKENS",
        "API_BEARER",
    )
    tokens: Set[str] = set()
    for k in keys:
        v = (os.getenv(k) or "").strip()
        if not v:
            continue
        if ("," in v) or (";" in v):
            tokens |= _split_tokens(v)
        else:
            tokens.add(v)
    # הסרת ריקים בטעות
    tokens = {t for t in tokens if t}
    return tokens

_TOKENS: Set[str] = _load_tokens_from_env()

_ALLOW_ALL = (os.getenv("SECURITY_ALLOW_ALL", "0").strip().lower() in ("1", "true", "yes", "on"))

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────
def _const_eq(a: str, b: str) -> bool:
    """השוואה בטוחה בזמן קבוע ככל האפשר."""
    try:
        return hmac.compare_digest(a, b)
    except Exception:
        return a == b  # fallback

def _extract_bearer(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    parts = authorization.strip().split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return None

def _any_token_matches(candidate: Optional[str]) -> bool:
    if not candidate:
        return False
    # חשוב לעבור על כל הסט ולהשתמש ב־compare_digest כדי להימנע מדליפת זמן
    for t in _TOKENS:
        if _const_eq(candidate, t):
            return True
    return False

# אופציונלי: לאפשר רענון ידני של הטוקנים בלי ריסטארט (אם תרצה לקרוא מכאן מאנדפוינט אדמין)
def refresh_tokens_from_env() -> int:
    global _TOKENS
    _TOKENS = _load_tokens_from_env()
    return len(_TOKENS)

# ──────────────────────────────────────────────────────────────────────────────
# FastAPI dependency
# מקבל גם Authorization: Bearer, גם x-api-key, וגם api_key ב-query.
# ──────────────────────────────────────────────────────────────────────────────
async def require_api_key(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None),
) -> None:
    if _ALLOW_ALL:
        return

    token = _extract_bearer(authorization)
    if not token:
        # נסה header חלופי
        token = (x_api_key or "").strip() or None
    if not token:
        # נסה query param כ־fallback (למשל ?api_key=...)
        qp = request.query_params.get("api_key")
        token = qp.strip() if qp else None

    if not _any_token_matches(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # אחרת: מאושר
    return









































































































































































