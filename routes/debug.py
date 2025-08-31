from __future__ import annotations
from fastapi import APIRouter, Query
from typing import Dict, Any
import os, platform, time
try:
    import psutil
except Exception:
    psutil = None  # type: ignore

router = APIRouter(prefix="/debug", tags=["Debug"])

def _tokens_from_env() -> list[str]:
    def _split(val: str | None) -> list[str]:
        if not val: return []
        s = val.replace("\n", ",").replace(";", ",")
        return [t.strip() for t in s.split(",") if t.strip()]
    toks = []
    for key in ("API_BEARER_TOKEN", "API_BEARER_TOKEN_ALT", "ALGOGPT_TOKENS"):
        v = os.getenv(key)
        if key == "ALGOGPT_TOKENS":
            toks.extend(_split(v))
        elif v:
            toks.append(v.strip())
    masked = []
    for t in toks:
        masked.append("***" if len(t) <= 6 else f"{t[:3]}…{t[-3:]}")
    return masked

@router.get("/")
def debug_router(op: str = Query("ping", pattern="^(ping|health|tokens|refresh)$")) -> Dict[str, Any]:
    if op == "ping":
        return {"ok": True, "pong": "ok"}
    if op == "health":
        mem, cpu = {}, None
        if psutil:
            vm = psutil.virtual_memory()
            mem = {
                "total_mb": round(vm.total/(1024*1024),2),
                "used_mb": round(vm.used/(1024*1024),2),
                "free_mb": round(vm.available/(1024*1024),2),
                "percent": vm.percent,
            }
            cpu = psutil.cpu_percent(interval=0.3)
        else:
            mem = {"note":"psutil not installed"}
        return {
            "ok": True,
            "env": os.getenv("ENV","production"),
            "platform": platform.platform(),
            "time": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
            "cpu_percent": cpu,
            "memory": mem,
        }
    if op == "tokens":
        tm = _tokens_from_env()
        return {"ok": True, "count": len(tm), "tokens_masked": tm}
    if op == "refresh":
        return {"ok": False, "detail": "Token refresh requires process restart."}











