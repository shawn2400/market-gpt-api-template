from fastapi import FastAPI
import os

app = FastAPI()

def _mode() -> str:
    force = (os.getenv("ROUTES_ONLY") or "").strip().lower()
    if force in ("live", "dry"):
        return force
    return "live" if (os.getenv("EXECUTE_TRADES", "0").lower() in ("1","true","yes","on")) else "dry"

@app.get("/ping")
def ping():
    return {"ok": True, "mode": _mode()}





