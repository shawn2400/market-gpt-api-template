# utils/bigjson.py
from __future__ import annotations
import os
import json
import time
import uuid
from pathlib import Path
from fastapi.responses import JSONResponse

CACHE_DIR = Path("static/cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

def respond_or_dump_to_file(data, max_bytes: int = 1_048_576, prefix: str = "dump") -> JSONResponse:
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
    if len(raw) <= max_bytes:
        return JSONResponse(content=data)
    # שמירה לקובץ
    ts = int(time.time())
    name = f"{prefix}_{ts}_{uuid.uuid4().hex}.json"
    path = CACHE_DIR / name
    with open(path, "wb") as f:
        f.write(raw)
    return JSONResponse(
        content={
            "detail": "payload too large – served as file",
            "size_bytes": len(raw),
            "url": f"/static/cache/{name}",
            "expires_hint": "מנקה אוטומטית כל שעה; קבצים ישנים נמחקים אחרי 24h"
        },
        headers={"X-Response-Offloaded": "1"}
    )
