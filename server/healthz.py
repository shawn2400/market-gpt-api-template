#!/usr/bin/env python3
# healthz.py
from __future__ import annotations
import os, sys, json, time
from typing import Any, Dict

try:
    import httpx
except Exception as e:
    print(json.dumps({"ok": False, "error": f"missing httpx: {e}"}))
    sys.exit(2)

PORT = int(os.getenv("PORT", "10000"))
HOST = os.getenv("HOST", "127.0.0.1")
BASE = f"http://{HOST}:{PORT}"

def _get(url: str) -> Dict[str, Any]:
    try:
        with httpx.Client(timeout=5.0) as c:
            r = c.get(url)
            return {"status": r.status_code, "json": r.json()}
    except Exception as e:
        return {"status": 0, "error": str(e)}

def main() -> int:
    t0 = time.time()
    h = _get(f"{BASE}/health")
    r = _get(f"{BASE}/readyz")
    took = round((time.time() - t0) * 1000.0, 1)
    out: Dict[str, Any] = {"ok": False, "took_ms": took, "health": h, "readyz": r}

    # החלטה: health 200 + readyz.ok True → OK
    health_ok = h.get("status") == 200 and isinstance(h.get("json"), dict)
    ready_ok = r.get("status") == 200 and isinstance(r.get("json"), dict) and bool(r["json"].get("ok"))
    out["ok"] = bool(health_ok and ready_ok)

    print(json.dumps(out, ensure_ascii=False))
    return 0 if out["ok"] else 1

if __name__ == "__main__":
    sys.exit(main())

