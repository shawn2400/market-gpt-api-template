# utils/scanner_utils.py

import asyncio, logging, os
from utils.get_klines import get_klines
from utils.indicators import compute_indicators
from utils.binance_client import client
from utils.quality_score import compute_quality_score
from utils.ai_analysis import predict_optimal_sl_tp
from utils.trending_utils import get_trending_symbols

# הגבלת סריקות במקביל (ברירת מחדל: 15)
semaphore = asyncio.Semaphore(int(os.getenv("MAX_CONCURRENT_SCANS", 15)))

def get_symbols(market_type="futures", min_volume=1_000_000, trending_only=False):
    try:
        info = client.futures_exchange_info() if market_type == "futures" else client.get_exchange_info()
        syms = [
            x["symbol"] for x in info["symbols"]
            if x["quoteAsset"] == "USDT" and x["status"] == "TRADING"
        ]
        if trending_only:
            tr = set(get_trending_symbols(trending_source=None, market_type=market_type))
            syms = [s for s in syms if s in tr]
        out = []
        for s in syms:
            try:
                tk = client.futures_ticker(symbol=s) if market_type == "futures" else client.get_ticker(symbol=s)
                if float(tk.get("quoteVolume", 0)) >= min_volume:
                    out.append(s)
            except Exception:
                continue
        return out
    except Exception as e:
        logging.error(f"[scanner_utils] {e}")
        return ["BTCUSDT", "ETHUSDT", "BNBUSDT"]

async def safe_get_klines(symbol, interval="1m", limit=50, market_type="futures"):
    try:
        df = get_klines(symbol, interval, limit, market_type)
        if df is None or df.empty:
            return None
        return df
    except Exception:
        return None

async def analyze_symbol(
    symbol: str,
    market_type: str = "futures",
    interval: str = "1m",
    limit: int = 50,
    min_volume: int = 1_000_000,
    trending_only: bool = False,
    with_ai: bool = True,
    frames: list[str] | None = None
):
    async with semaphore:
        df = await safe_get_klines(symbol, interval, limit, market_type)
        if df is None or len(df) < 30:
            return None
        df = compute_indicators(df)
        if df.empty:
            return None
        last = df.iloc[-1]
        direction = (
            "LONG" if last["rsi"] < 35 and last["adx"] > 20 and last["close"] > last["ema_21"]
            else "SHORT" if last["rsi"] > 70 and last["adx"] > 20 and last["close"] < last["ema_21"]
            else "NEUTRAL"
        )
        if direction == "NEUTRAL":
            return None
        qs = compute_quality_score(df)
        sltp = predict_optimal_sl_tp(direction, last["close"]) if with_ai else {"sl": None, "tp": None}
        return {
            "symbol": symbol,
            "market_type": market_type,
            "close": float(last["close"]),
            "volume": float(last["volume"]),
            "direction": direction,
            "quality_score": int(qs),
            "sl": sltp["sl"],
            "tp": sltp["tp"],
            "frames": frames or [interval]
        }

async def scan_all(
    market_type: str = "futures",
    interval: str = "1m",
    limit: int = 50,
    min_quality: int = 5,
    trending_only: bool = False,
    min_volume: int = 1_000_000,
    with_ai: bool = True
):
    syms = get_symbols(market_type, min_volume, trending_only)[:limit]
    tasks = [
        analyze_symbol(
            s, market_type, interval, limit,
            min_volume, trending_only, with_ai
        ) for s in syms
    ]
    raw = await asyncio.gather(*tasks)
    filt = [r for r in raw if r and r["quality_score"] >= min_quality]
    filt.sort(key=lambda x: (-x["quality_score"], -x["volume"]))
    return filt[:5]

























































