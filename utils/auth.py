# utils/auth.py
from __future__ import annotations
import os, re, logging
from typing import Optional, Set, List

logger = logging.getLogger("algogpt.auth")

_TOKENS: Set[str] = set()
_PUBLIC_PATHS: Set[str] = set()
_PUBLIC_PREFIXES: List[str] = []
_ALLOW_ALL: bool = False

def _split_multi(s: str) -> list[str]:
    return [x for x in re.split(r"[,\n\r\t ]+", (s or "").strip()) if x]

def _read_tokens_from_env() -> Set[str]:
    toks: list[str] = []
    env = os.getenv("API_TOKENS", "")
    if env:
        toks += re.split(r"[,\s]+", env.strip())
    fp = os.getenv("API_TOKENS_FILE")
    if fp and os.path.isfile(fp):
        try:
            with open(fp, "r", encoding="utf-8") as fh:
                toks += [ln.strip() for ln in fh if ln.strip()]
        except Exception as e:
            logger.warning("auth: failed reading API_TOKENS_FILE %s: %s", fp, e)
    return {t for t in (x.strip() for x in toks) if t}

def _read_public_from_env() -> None:
    global _PUBLIC_PATHS, _PUBLIC_PREFIXES, _ALLOW_ALL
    _ALLOW_ALL = os.getenv("SECURITY_ALLOW_ALL", "0").lower() in ("1","true","on","yes")
    if os.getenv("SECURITY_PUBLIC_STATUS", "0").lower() in ("1","true","on","yes"):
        _PUBLIC_PATHS = set(_split_multi(os.getenv("SECURITY_PUBLIC_PATHS", "")))
        _PUBLIC_PREFIXES = _split_multi(os.getenv("SECURITY_PUBLIC_PREFIXES", ""))
    else:
        _PUBLIC_PATHS = set()
        _PUBLIC_PREFIXES = []

def refresh_tokens_from_env() -> None:
    global _TOKENS
    _TOKENS = _read_tokens_from_env()
    _read_public_from_env()
    logger.info(
        "auth: loaded %d token(s). public_paths=%s prefixes=%s",
        len(_TOKENS), sorted(_PUBLIC_PATHS), _PUBLIC_PREFIXES
    )

# load on import
refresh_tokens_from_env()

def allow_all() -> bool:
    return _ALLOW_ALL

def extract_token(request, authorization: Optional[str] = "", x_api_key: Optional[str] = None) -> Optional[str]:
    if authorization and authorization.lower().startswith("bearer "):
        try:
            return authorization.split(None, 1)[1].strip()
        except Exception:
            pass
    if x_api_key:
        return x_api_key.strip()
    try:
        qp = request.query_params.get("api_key")
        if qp:
            return qp.strip()
    except Exception:
        pass
    return None

def token_matches(token: Optional[str]) -> bool:
    return bool(token and token in _TOKENS)

def get_loaded_tokens(mask: bool = True):
    if mask:
        return [f"{t[:3]}***{t[-2:]}" if len(t) > 5 else "***" for t in sorted(_TOKENS)]
    return sorted(_TOKENS)

def get_public_paths():
    return {"paths": sorted(_PUBLIC_PATHS), "prefixes": list(_PUBLIC_PREFIXES)}

















































































































































































