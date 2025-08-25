# alerts_app.py
from __future__ import annotations
import os
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware

load_dotenv(override=False)

app = FastAPI(title="AlgoGPT Alerts (Standalone)")

app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

from routes.alerts import router as alerts_router
app.include_router(alerts_router)

@app.get("/")
async def root():
    return {"ok": True, "service": "alerts-only"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("alerts_app:app", host="0.0.0.0", port=int(os.getenv("PORT", 10000)), reload=False)
