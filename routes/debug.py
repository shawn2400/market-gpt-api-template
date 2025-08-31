# routes/debug.py
from __future__ import annotations
from fastapi import APIRouter, Query
from typing import Dict, Any
import os, platform, time

try:
    import psutil  # אופציונלי
except Exception:
    psutil = None  # type: ignore

router = APIRouter(prefix="/debug", tags=["Debug"])

def _tokens_from_env_masked() -> list[str]:
    def _split(val: str | None) -> list[str]:
        if not val:
            return []
        s = val.replace("\n", ",").replace(";", ",")
        return [t.strip() for t in s.split(",") if t.strip()]
    toks: list[str] = []
    # תומך בשלוש הדרכים לטעינת טוקנים
    if os.getenv("API_BEARER_TOKEN"):
        toks.append(os.getenv("API_BEARER_TOKEN", "").strip())
    if os.getenv("API_BEARER_TOKEN_ALT"):
        toks.append(os.getenv("API_BEARER_TOKEN_ALT", "").strip())
    toks.extend(_split(os.getenv("ALGOGPT_TOKENS")))
    # מסכה חלקית
    masked: list[str] = []
    for t in toks:
        if not t:
            continue
        masked.append("***" if len(t) <= 6 else f"{t[:3]}…{t[-3:]}")
    return masked

# תומך גם /debug וגם /debug/
@router.get("")
@router.get("/")
def debug_router(
    op: str = Query("ping", regex="^(ping|health|tokens|refresh)$")  # NOTE: regex (תואם Pydantic v1)
) -> Dict[str, Any]:
    if op == "ping":
        return {"ok": True, "pong": "ok"}

    if op == "health":
        mem: Dict[str, Any]
        cpu = None
        if psutil:
            vm = psutil.virtual_memory()
            mem = {
                "total_mb": round(vm.total / (1024 * 1024), 2),
                "used_mb": round(vm.used / (1024 * 1024), 2),
                "free_mb": round(vm.available / (1024 * 1024), 2),
                "percent": vm.percent,
            }
            cpu = psutil.cpu_percent(interval=0.3)
        else:
            mem = {"note": "psutil not installed"}
        return {
            "ok": True,
            "env": os.getenv("ENV", "production"),
            "platform": platform.platform(),
            "time": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
            "cpu_percent": cpu,
            "memory": mem,
        }

    if op == "tokens":
        return {"ok": True, "count": len(_tokens_from_env_masked()), "tokens_masked": _tokens_from_env_masked()}

    if op == "refresh":
        # אין ריפרש דינמי – טעינת טוקנים נעשית בסטארטאפ; נדרש ריסטארט פרוסס
        return {"ok": False, "detail": "Token refresh requires process restart."}

    # לא אמור להגיע לכאן (regex מגביל), אבל לשקט:
    return {"ok": False, "detail": "Unknown op"}












