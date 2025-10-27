# routes/debug_signature.py (או בתוך main.py תחת דגל ENV)
from fastapi import APIRouter, Request, Depends, HTTPException
import hashlib, json, os
router = APIRouter()

def _ops_protected(request: Request):
    token = os.getenv("API_BEARER_TOKEN","")
    auth = request.headers.get("Authorization","")
    if not token or not auth.lower().startswith("bearer "):
        raise HTTPException(401, "Unauthorized")
    if not hmac.compare_digest(auth.split(" ",1)[1], token):
        raise HTTPException(401, "Unauthorized")

@router.post("/ops/sig-echo")
async def sig_echo(request: Request, _: None = Depends(_ops_protected)):
    b = await request.body()
    body_sha = hashlib.sha256(b).hexdigest()
    try:
        outer = json.loads(b.decode())
        inner_str = json.dumps(outer["body"], separators=(",",":"), sort_keys=True)
        inner_sha = hashlib.sha256(inner_str.encode()).hexdigest()
    except Exception:
        inner_str, inner_sha = None, None

    # מחזירים את מה שהשרת ינסה לחתום עליו
    return {
        "method": request.method,
        "path":   str(request.url.path),
        "headers_seen": {
            "X-OPS-Nonce":      request.headers.get("X-OPS-Nonce") or request.headers.get("X-Nonce"),
            "X-OPS-Timestamp":  request.headers.get("X-OPS-Timestamp") or request.headers.get("X-Timestamp"),
            "X-OPS-Ts":         request.headers.get("X-OPS-Ts") or request.headers.get("X-Ts"),
            "X-OPS-Signature":  request.headers.get("X-OPS-Signature") or request.headers.get("X-Signature"),
        },
        "hashes": {
            "body_sha256":  body_sha,
            "inner_sha256": inner_sha,
        },
        "canon_candidates": [
            "METHOD\\nPATH\\nNONCE\\nTS\\nSHA256(body)",
            "NONCE\\nTS\\nSHA256(body)",
            "METHOD\\nPATH\\nNONCE\\nTS\\nSHA256(inner)",
            "NONCE\\nTS\\nSHA256(inner)"
        ]
    }
