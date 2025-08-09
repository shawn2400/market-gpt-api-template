import os
import logging
from fastapi import FastAPI, Depends, HTTPException, Security, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional

# לטעון משתני סביבה
from dotenv import load_dotenv
load_dotenv()

# הגדרות בסיסיות
API_TOKEN = os.getenv("API_BEARER_TOKEN", "your_default_token_here")  # להגדיר במשתני סביבה

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s: %(message)s')

app = FastAPI(
    title="AlgoGPT API",
    description="AlgoGPT הוא סוחר אלגוריתמי בזמן אמת עבור Binance. כולל Futures, Spot, Grid, AI, דוחות ו־Auto Executor.",
    version="2.0.7",
    openapi_url="/openapi.json",
    docs_url="/docs"
)

# CORS - במידת הצורך
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # במידת הצורך, להגביל את המקורות
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# אבטחה - Bearer Token פשוט
bearer_scheme = HTTPBearer()

def verify_token(credentials: HTTPAuthorizationCredentials = Security(bearer_scheme)):
    token = credentials.credentials
    if token != API_TOKEN:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing token")
    return True

# --- Models ---

class TradeRequest(BaseModel):
    symbol: str
    side: str  # "LONG" או "SHORT"
    entry: Optional[float] = None
    sl: Optional[float] = None
    tp: Optional[float] = None
    budget: Optional[float] = 100
    leverage: Optional[int] = 10

class GridTradeRequest(BaseModel):
    symbol: str
    budget: float
    grid_count: Optional[int] = 6
    grid_pct: Optional[float] = 0.4
    leverage: Optional[int] = 20
    futures: Optional[bool] = True
    tp_pct: Optional[float] = 1.5
    sl_pct: Optional[float] = 1

class AiAnalyzeRequest(BaseModel):
    symbol: str
    rsi: float
    adx: float
    trend: str
    pattern: str
    volume: float

# --- Dummy Handlers (יש להחליף ללוגיקה אמיתית) ---

@app.get("/", tags=["Config"])
async def check_server_status():
    return {"status": "ok", "message": "Server is running"}

@app.post("/trade", tags=["Trades"], dependencies=[Depends(verify_token)])
async def place_trade(trade: TradeRequest):
    logging.info(f"Received trade request: {trade}")
    # כאן יש לממש את הלוגיקה לביצוע טרייד חי
    return {"status": "success", "message": "Trade executed", "trade": trade.dict()}

@app.get("/scan/multi", tags=["Trades"], dependencies=[Depends(verify_token)])
async def scan_multi(
    interval: str = "15m",
    min_quality: int = 6,
    top: int = 10,
    market_type: str = "futures",
    trending_only: bool = False,
    trending_source: str = "coingecko"
):
    logging.info(f"Scanning market: interval={interval}, min_quality={min_quality}, top={top}, market_type={market_type}, trending_only={trending_only}, trending_source={trending_source}")
    # לממש לוגיקת סריקה
    return {"results": []}

@app.post("/grid/trade", tags=["Grid"], dependencies=[Depends(verify_token)])
async def execute_grid(grid_trade: GridTradeRequest):
    logging.info(f"Received grid trade request: {grid_trade}")
    # לממש פתיחת גריד
    return {"status": "success", "message": "Grid commands sent", "grid_trade": grid_trade.dict()}

@app.post("/ai-analyze", tags=["AI"], dependencies=[Depends(verify_token)])
async def ai_analyze(request: AiAnalyzeRequest):
    logging.info(f"Received AI analyze request: {request}")
    # לממש ניתוח GPT אמיתי
    return {"status": "success", "analysis": {}}

@app.get("/price", tags=["Trades"], dependencies=[Depends(verify_token)])
async def get_price(symbol: str):
    logging.info(f"Request current price for {symbol}")
    # לממש שאילת מחיר חי מביננס
    return {"symbol": symbol, "price": 123.45}

@app.get("/executor/start", tags=["Executor"], dependencies=[Depends(verify_token)])
async def start_executor():
    logging.info("Auto executor started")
    # לממש התחלת לולאת אוטומציה
    return {"status": "started"}

@app.get("/executor/stop", tags=["Executor"], dependencies=[Depends(verify_token)])
async def stop_executor():
    logging.info("Auto executor stopped")
    # לממש עצירת לולאת אוטומציה
    return {"status": "stopped"}

@app.get("/executor/status", tags=["Executor"], dependencies=[Depends(verify_token)])
async def executor_status():
    # לממש סטטוס ריצה
    running = False
    return {"running": running}

# --- הרצת האפליקציה (להריץ ב-gunicorn או uvicorn) ---

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)), log_level="info")




















