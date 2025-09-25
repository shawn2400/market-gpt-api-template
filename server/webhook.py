from __future__ import annotations
import os, logging
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("algogpt.webhook")

app = FastAPI(title="AlgoGPT Webhook")

def _resolve_mode() -> str:
    # FORCE_MODE דרך ENV קיים אצלך: ROUTES_ONLY=live|dry
    force = (os.getenv("ROUTES_ONLY") or "").strip().lower()
    if force in ("live", "dry"):
        return force
    # אם אין, נגזר מ-EXECUTE_TRADES
    exec_trades = (os.getenv("EXECUTE_TRADES", "0").strip().lower() in ("1", "true", "yes", "on"))
    return "live" if exec_trades else "dry"

@app.get("/ping")
async def ping():
    return JSONResponse({"ok": True, "mode": _resolve_mode()})

@app.get("/mode")
async def mode_get():
    return JSONResponse({"ok": True, "mode": _resolve_mode()})

@app.post("/telegram/webhook")
async def telegram_webhook(req: Request):
    # ACK בלבד כדי למנוע רטריי מטלגרם
    try:
        body = await req.json()
        log.info({
            "event": "tg_update",
            "has_message": bool(body.get("message")),
            "has_callback": bool(body.get("callback_query"))
        })
    except Exception as e:
        log.warning({"event": "tg_bad_update", "err": str(e)})
    return JSONResponse({"ok": True})

if __name__ == "__main__":
    # מאפשר הרצה ישירה מהקובץ (עוקף בעיות import של uvicorn server.webhook:app)
    import uvicorn
    port = int(os.getenv("PORT", "11000"))  # אפשר לשנות ל-10000 אם פנוי
    uvicorn.run(app, host="0.0.0.0", port=port)





