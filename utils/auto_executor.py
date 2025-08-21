# utils/auto_executor.py
import asyncio, logging, requests, pandas as pd, time, json
from collections import deque
from utils import config as cfg
from utils.binance_client import binance_client
from utils.indicators import prepare_indicators_for_backtest
from utils import cache_fallback as redis_store  # ✅ לשמירה ב-Redis

logger = logging.getLogger("algogpt.autoexec")

FUTURES_BASE = "https://fapi.binance.com"

EXECUTOR_RUNNING = False
EXECUTOR_SYMBOLS: list[str] = []
EXECUTOR_LAST_TS: float | None = None
EXECUTOR_LOGS: deque[dict] = deque(maxlen=200)
EXECUTOR_TRADES: deque[dict] = deque(maxlen=500)  # ✅ טריידים בזיכרון


def _log(event: str, symbol: str | None = None, level: str = "INFO", **kwargs):
    record = {
        "time": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
        "event": event,
        "symbol": symbol,
        "level": level,
        **kwargs,
    }
    EXECUTOR_LOGS.append(record)
    if level == "ERROR":
        logger.error(record)
    elif level == "WARNING":
        logger.warning(record)
    else:
        logger.info(record)


async def _save_trade_to_history(trade: dict):
    """שומר טרייד גם בזיכרון וגם ב־Redis"""
    EXECUTOR_TRADES.append(trade)
    try:
        key = "trades:history"
        await redis_store.lpush(key, json.dumps(trade))
        await redis_store.ltrim(key, 0, 500)  # שומר עד 500 טריידים אחרונים
    except Exception as e:
        _log("trade_history_save_error", level="ERROR", error=str(e))


async def scan_and_trade(symbol: str):
    try:
        _log("scan_start", symbol=symbol)
        url = f"{FUTURES_BASE}/fapi/v1/klines"
        r = requests.get(url, params={"symbol": symbol, "interval": "15m", "limit": 200}, timeout=10)
        r.raise_for_status()
        arr = r.json()

        cols = ["open_time","open","high","low","close","volume","close_time","qv","nTrades","taker_base","taker_quote","x"]
        df = pd.DataFrame(arr, columns=cols[:len(arr[0])])
        for c in ("open","high","low","close","volume"):
            df[c] = pd.to_numeric(df[c], errors="coerce")

        ind = prepare_indicators_for_backtest(df)
        if ind.empty:
            _log("scan_no_data", symbol=symbol, level="WARNING")
            return

        row = ind.iloc[-1].to_dict()
        decision = {
            "symbol": symbol,
            "ts": time.time(),
            "indicators": row,
        }

        # ✅ שמירה ל־Redis
        await _save_trade_to_history(decision)

        _log("scan_ok", symbol=symbol, indicators=row)

    except Exception as e:
        _log("scan_error", symbol=symbol, level="ERROR", error=str(e))

















































































