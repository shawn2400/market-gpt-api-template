# כל הקבצים יועברו בגרסה מלאה, מוכנה לעבודה.

# 1. utils/backtest_runner.py
from __future__ import annotations
import pandas as pd
from utils.indicators import prepare_indicators_for_backtest

def run_backtest(df: pd.DataFrame, strategy: str = "ema_crossover", initial_balance: float = 1000.0) -> dict:
    df_ind = prepare_indicators_for_backtest(df)
    df = df.join(df_ind.drop(columns=df.columns, errors="ignore"))

    balance = initial_balance
    position = None
    entry_price = 0.0
    trades = 0
    max_drawdown = 0.0
    peak = balance

    for i in range(1, len(df)):
        row = df.iloc[i]
        ema21 = row.get("ema_21", 0)
        ema50 = row.get("ema_50", 0)
        close = row["close"]

        if strategy == "ema_crossover":
            if not position and ema21 > ema50:
                position = True
                entry_price = close
                trades += 1
            elif position and ema21 < ema50:
                balance *= (1 + (close - entry_price) / entry_price)
                position = None

        peak = max(peak, balance)
        dd = 1 - (balance / peak)
        max_drawdown = max(max_drawdown, dd)

    final_balance = balance
    profit_pct = ((final_balance - initial_balance) / initial_balance) * 100.0

    return {
        "final_balance": final_balance,
        "profit_pct": profit_pct,
        "n_trades": trades,
        "stress": {
            "max_drawdown_pct": max_drawdown * 100.0,
            "max_win_pct": max(0, profit_pct),
            "risk_reward_ratio": profit_pct / max_drawdown if max_drawdown > 0 else None,
        }
    }

# 2. utils/export_utils.py
import csv, os, json
from fastapi.responses import FileResponse
from pathlib import Path
from typing import List, Dict, Any

EXPORT_DIR = Path("static/exports")
EXPORT_DIR.mkdir(parents=True, exist_ok=True)

def export_trades_csv(trades: List[Dict[str, Any]]) -> FileResponse:
    fname = EXPORT_DIR / "trades_export.csv"
    with open(fname, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=trades[0].keys())
        writer.writeheader()
        writer.writerows(trades)
    return FileResponse(fname, filename="trades_export.csv")

# 3. utils/pnl_summary.py
from __future__ import annotations
from typing import List, Dict

def summarize_pnl(trades: List[Dict]) -> Dict:
    total = len(trades)
    total_pnl = sum(t.get("pnl", 0) for t in trades)
    win_rate = sum(1 for t in trades if t.get("pnl", 0) > 0) / total if total else 0
    avg_pnl = total_pnl / total if total else 0
    return {
        "total": total,
        "win_rate": round(win_rate * 100, 2),
        "total_pnl": round(total_pnl, 2),
        "avg_pnl": round(avg_pnl, 2),
    }

# 4. utils/chop_viewer.py
from __future__ import annotations
import pandas as pd

# חישוב פשוט של אזורים מדשדשים לפי BBWidth או ADX נמוך

def detect_chop_zones(df: pd.DataFrame, adx_thresh: float = 18.0) -> pd.DataFrame:
    df = df.copy()
    if "adx" not in df.columns:
        return df
    df["chop"] = df["adx"] < adx_thresh
    return df

# 5. routes/export.py
from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from utils.auth import require_api_key
from utils.trade_manager import get_trade_history
from utils.export_utils import export_trades_csv

router = APIRouter(
    prefix="/export",
    tags=["Export"],
    dependencies=[Depends(require_api_key)]
)

@router.get("/trades.csv")
def export_trades_csv_route():
    trades = get_trade_history(limit=200)
    return export_trades_csv(trades)

# 6. routes/pnl.py
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Dict, Any
from utils.auth import require_api_key
from utils.trade_manager import get_trade_history
from utils.pnl_summary import summarize_pnl

router = APIRouter(
    prefix="/pnl",
    tags=["PnL"],
    dependencies=[Depends(require_api_key)]
)

class PnLSummaryResponse(BaseModel):
    ok: bool = True
    summary: Dict[str, Any]

@router.get("/summary", response_model=PnLSummaryResponse)
def pnl_summary():
    trades = get_trade_history(limit=500)
    summary = summarize_pnl(trades)
    return PnLSummaryResponse(ok=True, summary=summary)

# 7. routes/chop.py
from fastapi import APIRouter, Query, HTTPException
import pandas as pd
import requests
from utils.chop_viewer import detect_chop_zones

router = APIRouter(prefix="/chop", tags=["Chop Zones"])

@router.get("/{symbol}")
def chop_zones(symbol: str, interval: str = Query("1h"), limit: int = Query(100)):
    url = f"https://fapi.binance.com/fapi/v1/klines"
    r = requests.get(url, params={"symbol": symbol, "interval": interval, "limit": limit}, timeout=10)
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail="Binance error")
    df = pd.DataFrame(r.json(), columns=["open_time","open","high","low","close","volume","close_time",
                                         "qv","nTrades","taker_base","taker_quote","x"])
    for c in ("open","high","low","close","volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = detect_chop_zones(df)
    return df[["open_time", "close", "adx", "chop"]].tail(10).to_dict(orient="records")

# 8. routes/ui.py
from fastapi import APIRouter
from fastapi.responses import FileResponse
from pathlib import Path

router = APIRouter(tags=["UI"])

@router.get("/dashboard")
def dashboard_ui():
    path = Path("static/dashboard/index.html")
    if path.exists():
        return FileResponse(path)
    return {"error": "dashboard not found"}

# 9. main.py — תוודא שנוסף:
# EXTRA_ROUTERS.append(("routes.export", "router"))
# EXTRA_ROUTERS.append(("routes.pnl", "router"))
# EXTRA_ROUTERS.append(("routes.chop", "router"))
# EXTRA_ROUTERS.append(("routes.ui", "router"))

