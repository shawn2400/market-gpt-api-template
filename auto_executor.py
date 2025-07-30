# ===== scanner_utils.py =====

import asyncio
import logging
import os
from utils.get_klines import get_klines
from utils.indicators import compute_indicators
from utils.binance_client import client
from utils.quality_score import compute_quality_score
from utils.ai_analysis import predict_optimal_sl_tp
from utils.trending_utils import get_trending_symbols

semaphore = asyncio.Semaphore(int(os.getenv("MAX_CONCURRENT_SCANS", 15)))

def get_symbols(
    market_type="futures",
    min_volume=1_000_000,
    trending_only=False,
    max_symbols=500
):
    """
    מחזיר רשימת סמלים פעילים (TRADING) לפי שוק, Trending, ו־Volume.
    """
    try:
        if market_type == "futures":
            info = client.futures_exchange_info()
        elif market_type == "spot":
            info = client.get_exchange_info()
        else:
            raise ValueError("market_type must be 'futures' or 'spot'")

        all_symbols = [
            x['symbol'] for x in info['symbols']
            if x['quoteAsset'] == 'USDT' and x['status'] == 'TRADING'
        ]

        # Trending Only
        if trending_only:
            trending = set(get_trending_symbols())
            symbols = [s for s in all_symbols if s in trending]
        else:
            symbols = all_symbols

        # Volume filter
        filtered = []
        for s in symbols[:max_symbols]:
            try:
                ticker = client.futures_ticker(symbol=s) if market_type == "futures" else client.get_ticker(symbol=s)
                vol = float(ticker.get('quoteVolume', 0))
                if vol >= min_volume:
                    filtered.append(s)
            except Exception:
                continue
        return filtered
    except Exception as e:
        logging.error(f"[!] שגיאה בשליפת סמלים ({market_type}): {e}")
        # ברירת מחדל ל־TOP4 כדי שהמערכת לא תקרוס
        return ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"]

async def safe_get_klines(symbol, interval="1m", limit=50, market_type="futures"):
    try:
        df = get_klines(symbol=symbol, interval=interval, limit=limit, market_type=market_type)
        if df is None or df.empty:
            logging.warning(f"[{symbol}] אין נתוני נרות (empty).")
            return None
        return df
    except Exception as e:
        logging.warning(f"[{symbol}] שגיאה בשליפת נרות: {type(e).__name__} – {e}")
        return None

async def analyze_symbol(
    symbol: str,
    market_type: str = "futures",
    interval: str = "1m",
    limit: int = 50,
    min_volume: int = 1_000_000,
    trending_only: bool = False,
    with_ai: bool = True,
    frames: list = None
):
    async with semaphore:
        await asyncio.sleep(0.2)
        df = await safe_get_klines(symbol, interval, limit, market_type)
        if df is None or len(df) < 30:
            logging.warning(f"[{symbol}] אין מספיק נתונים ({market_type}) לניתוח.")
            return None
        df = compute_indicators(df)
        if df.empty:
            logging.warning(f"[{symbol}] אין נתונים לאחר חישוב אינדיקטורים.")
            return None
        last = df.iloc[-1]
        direction = (
            "LONG" if last["rsi"] < 35 and last["adx"] > 20 and last["close"] > last["ema_21"]
            else "SHORT" if last["rsi"] > 70 and last["adx"] > 20 and last["close"] < last["ema_21"]
            else "NEUTRAL"
        )
        quality_score = compute_quality_score(df)
        if direction == "NEUTRAL":
            return None
        sltp = predict_optimal_sl_tp(symbol, last["close"], direction) if with_ai else {"sl": None, "tp": None}
        out = {
            "symbol": symbol,
            "market_type": market_type,
            "close": float(last["close"]),
            "volume": float(last["volume"]),
            "direction": direction,
            "quality_score": int(quality_score),
            "sl": sltp.get("sl"),
            "tp": sltp.get("tp"),
            "frames": frames or [interval]
        }
        return out

async def scan_all(
    market_type: str = "futures",
    interval: str = "1m",
    limit: int = 50,
    min_quality: int = 5,
    trending_only: bool = False,
    min_volume: int = 1_000_000,
    with_ai: bool = True,
    max_symbols: int = 500
):
    symbols = get_symbols(
        market_type=market_type,
        min_volume=min_volume,
        trending_only=trending_only,
        max_symbols=max_symbols
    )[:limit]

    tasks = [
        analyze_symbol(
            symbol=s,
            market_type=market_type,
            interval=interval,
            limit=limit,
            min_volume=min_volume,
            trending_only=trending_only,
            with_ai=with_ai,
            frames=[interval]
        ) for s in symbols
    ]
    results = await asyncio.gather(*tasks)
    filtered = [
        r for r in results if r and r["quality_score"] >= min_quality and r["direction"] in ("LONG", "SHORT")
    ]
    filtered = sorted(filtered, key=lambda x: (-x["quality_score"], -x["volume"]))
    return filtered[:10]  # תחזיר TOP 10

# אפשר להוסיף כאן גם scan_multi_tf לסריקת Multi Timeframes אם תרצה.































