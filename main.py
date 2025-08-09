import os
import logging
from fastapi import FastAPI, Depends, HTTPException, Security, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware

from pydantic import BaseModel
from typing import Optional

from utils.ai_analysis import analyze_with_ai, predict_optimal_sl_tp
from utils.multi_tf_scanner import multi_tf_scan_with_ai
from utils.trade_executor import execute_trade_live
from utils.watchlist_utils import load_watchlist
from utils.ws_fallback import get_price, is_price_fresh

from dotenv import load_dotenv
load_dotenv()

API_TOKEN = os.getenv("API_BEARER_TOKEN", "secret-token")  # הכנס את הטוקן האמיתי שלך ב-env

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s: %(message)s')

app = FastAPI(title="AlgoGPT API", version="2.0.7")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

bearer_scheme = HTTPBearer()

def verify_token(credentials: HTTPAuthorizationCredentials = Security(bearer_scheme)):
    if credentials.credentials != API_TOKEN:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return True

class TradeRequest(BaseModel):
    symbol: str
    side: str
    entry: Optional[float] = None
    sl: Optional[float] = None
    tp: Optional[float] = None
    budget: Optional[float] = 100
    leverage: Optional[int] = 10

@app.get("/", tags=["Config"])
async def check_status():
    return {"status": "ok"}

@app.post("/trade", tags=["Trades"], dependencies=[Depends(verify_token)])
async def place_trade(trade: TradeRequest):
    logging.info(f"Place trade: {trade}")
    result = await execute_trade_live(
        symbol=trade.symbol,
        direction=trade.side,
        entry=trade.entry,
        stop=trade.sl,
        tp=trade.tp,
        leverage=trade.leverage,
        budget_usd=trade.budget,
        market_type="futures"
    )
    return result

@app.get("/scan/multi", tags=["Trades"], dependencies=[Depends(verify_token)])
async def scan_multi(
    interval: str = "15m,1h",
    min_quality: int = 6,
    top: int = 10,
    market_type: str = "futures",
    trending_only: bool = False,
    trending_source: str = "coingecko"
):
    timeframes = tuple(interval.split(","))
    results = await multi_tf_scan_with_ai(
        timeframes=timeframes,
        markets=(market_type,),
        min_quality=min_quality,
        top=top,
        trending_only=trending_only,
        trending_source=trending_source
    )
    return {"results": results}

# ניתן להוסיף מסלולים נוספים לפי הצורך





















