# alerts_app.py
from __future__ import annotations
import os
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
from utils.security import verify_hmac

load_dotenv(override=False)

app = FastAPI(title="AlgoGPT Alerts (Standalone)")

# ===== Middlewares =====
app.add_middleware(GZipMiddleware, minimum_size=1000)

CORS_ALLOWED = os.getenv("CORS_ALLOW_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOWED if CORS_ALLOWED != ["*"] else ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===== Routers =====
from routes.alerts import router as alerts_router
app.include_router(alerts_router)

@app.middleware("http")
async def verify_request_hmac(request: Request, call_next):
    """אימות HMAC אם מוגדר WEBHOOK_HMAC_SECRET"""
    raw = await request.body()
    sig = request.headers.get("X-Hub-Signature", "")
    if not verify_hmac(sig, raw):
        return {"ok": False, "error": "Invalid HMAC"}
    return await call_next(request)

@app.get("/")
async def root():
    return {"ok": True, "service": "alerts-only"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("alerts_app:app", host="0.0.0.0", port=int(os.getenv("PORT", 10000)), reload=False)

