# main.py

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import os

from dotenv import load_dotenv

from routes.ai import router as ai_router
from routes.trade import router as trade_router
from routes.grid import router as grid_router
from routes.multi_scan import router as multi_router

from auto_executor import start_executor_loop, stop_executor_loop, is_executor_running

load_dotenv()

app = FastAPI(
    title="AlgoGPT API",
    description="API למסחר בזמן אמת ב־Binance (Futures, Spot, Grid) כולל ניתוחים, דוחות, AI, SL/TP ודשבורד.",
    version="2.0.2"
)

# אפשר CORS אם יש צורך להתחבר מה-Frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# === Routers עיקריים ===
app.include_router(ai_router)
app.include_router(trade_router)
app.include_router(grid_router)
app.include_router(multi_router)


# === Status Endpoint ===
@app.get("/")
async def root():
    return {"status": "ok", "message": "AlgoGPT API is running ✅"}


# === Auto Executor Controls ===
@app.get("/executor/start")
async def start_executor():
    started = start_executor_loop()
    return {"status": "started" if started else "already running"}

@app.get("/executor/stop")
async def stop_executor():
    stopped = stop_executor_loop()
    return {"status": "stopped" if stopped else "not running"}

@app.get("/executor/status")
async def executor_status():
    running = is_executor_running()
    return {"running": running}


# === הרצה ישירה אם צריך מקומית ===
if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=10000, reload=True)




































































































































































































































































































































































































