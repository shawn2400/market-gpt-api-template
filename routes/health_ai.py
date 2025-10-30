# routes/health_ai.py
from fastapi import APIRouter, Header, HTTPException
import os, hmac, httpx

router = APIRouter()

def _ct_equal(a: str, b: str) -> bool:
    try:
        return hmac.compare_digest(a or "", b or "")
    except Exception:
        return (a or "") == (b or "")

def _auth_ok(tok: str) -> bool:
    for env in ("API_BEARER_TOKEN", "API_BEARER_TOKEN_RO", "API_BEARER_TOKEN_ACTION"):
        v = os.getenv(env, "")
        if v and _ct_equal(tok, f"Bearer {v}"):
            return True
    return False

@router.get("/readyz", tags=["Health"])
async def readyz():
    return "ok"

@router.post("/ai/test", tags=["Health"])
async def ai_test(authorization: str = Header(default="")):
    if not _auth_ok(authorization):
        raise HTTPException(status_code=401, detail="unauthorized")

    base = os.getenv("OPENAI_API_BASE", "https://api.deepseek.com/v1").rstrip("/")
    key  = os.getenv("OPENAI_API_KEY", "")
    model = os.getenv("DS_MODEL", "deepseek-chat")

    if not key:
        raise HTTPException(status_code=500, detail="missing OPENAI_API_KEY")

    payload = {
        "model": model,
        "messages": [
            {"role":"system","content":"Reply OK only."},
            {"role":"user","content":"ping"}
        ],
        "temperature": 0.1,
        "max_tokens": 8
    }

    headers = {"Authorization": f"Bearer {key}", "Content-Type":"application/json"}

    async with httpx.AsyncClient(timeout=10.0) as cli:
        r = await cli.post(f"{base}/chat/completions", json=payload, headers=headers)
        sample = (r.text or "")[:120]
        return {"ok": r.status_code == 200, "deepseek_status": r.status_code, "sample": sample}
