# server/webhook.py
from __future__ import annotations
import os, logging
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

log = logging.getLogger("algogpt.webhook")
app = FastAPI(title="AlgoGPT Minimal Webhook")

# ---- Mode resolution (NO new ENVs) ----
# FORCE_MODE: use ROUTES_ONLY if it's "live" or "dry"; else fall back to EXECUTE_TRADES.
def _resolve_mode() -> str:
    force = (os.getenv("ROUTES_ONLY") or "").strip().lower()
    if force in ("live", "dry"):
        return force
    exec_trades = (os.getenv("EXECUTE_TRADES", "0").strip().lower() in ("1", "true", "yes", "on"))
    return "live" if exec_trades else "dry"

_MODE = _resolve_mode()

@app.get("/ping")
async def ping():
    """No auth; quick health and current mode."""
    global _MODE
    # refresh on each call so you can flip ENV live/dry without restart
    _MODE = _resolve_mode()
    return JSONResponse({"ok": True, "mode": _MODE})

@app.post("/telegram/webhook")
async def telegram_webhook(req: Request):
    # keep it minimal; just acknowledge to avoid Telegram retries
    try:
        body = await req.json()
        log.info({"event": "tg_update", "has_message": bool(body.get("message"))})
    except Exception as e:
        log.warning({"event": "tg_bad_update", "err": str(e)})
    return JSONResponse({"ok": True})

@app.get("/mode")
async def mode_get():
    global _MODE
    _MODE = _resolve_mode()
    return JSONResponse({"ok": True, "mode": _MODE})

@app.post("/mode/{new_mode}")
async def mode_post(new_mode: str):
    """Runtime override using existing ROUTES_ONLY (no new envs).
       /mode/live or /mode/dry will just set the process-level cache.
       Real source of truth remains ROUTES_ONLY/EXECUTE_TRADES.
    """
    global _MODE
    nm = (new_mode or "").strip().lower()
    if nm not in ("live", "dry"):
        return JSONResponse({"ok": False, "error": "mode must be live|dry"}, status_code=400)
    _MODE = nm
    return JSONResponse({"ok": True, "mode": _MODE})



