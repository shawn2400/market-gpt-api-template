# utils/auto_executor.py
import asyncio
import logging
import requests
import pandas as pd
import time
from collections import deque
from typing import Optional, Dict, Any

from utils import config as cfg
from utils.indicators import prepare_indicators_for_backtest
from utils.binance_trader import binance_futures_trade

logger = logging.getLogger("algogpt.autoexec")

FUTURES_BASE = "https://fapi.binance.com"

# 🆕 משתנים גלובליים
EXECUTOR_RUNNING = False
EXECUTOR_SYMBOLS: list[str] = []
EXECUTOR_LAST_TS: float | None = None   # ✅ שומר מתי רץ לאחרונה
EXECUTOR_LOGS: deque[dict] = deque(maxlen=200)  # ✅ לוגים בזיכרון
EXECUTOR_TRADES: deque[dict] = deque(maxlen=200)  # ✅ היסטוריית טריידים


def _log(event: str, symbol: str | None = None, level: str = "INFO", **kwargs):
    """
    מוסיף גם ללוג של Python וגם ל־buffer בזיכרון
    """
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


def is_executor_running() -> bool:
    return EXECUTOR_RUNNING


# ---------------------------------------------------
# Scan + Trade Logic
# ---------------------------------------------------
async def scan_and_trade(symbol: str):
    try:
        _log("scan_start", symbol=symbol)

        # === Fetch klines ===
        url = f"{FUTURES_BASE}/fapi/v1/klines"
        r = requests.get(url, params={"symbol": symbol, "interval": "15m", "limit": 200}, timeout=10)
        r.raise_for_status()
        arr = r.json()

        cols = [
            "open_time","open","high","low","close","volume",
            "close_time","qv","nTrades","taker_base","taker_quote","x"
        ]
        df = pd.DataFrame(arr, columns=cols[:len(arr[0])])
        for c in ("open","high","low","close","volume"):
            df[c] = pd.to_numeric(df[c], errors="coerce")

        # === Indicators ===
        ind = prepare_indicators_for_backtest(df)
        if ind.empty:
            _log("scan_no_data", symbol=symbol, level="WARNING")
            return

        row = ind.iloc[-1].to_dict()
        _log("scan_ok", symbol=symbol, indicators=row)

        # === החלטת טרייד פשוטה (אפשר לשפר) ===
        side: Optional[str] = None
        if row.get("ema_fast") > row.get("ema_slow"):
            side = "LONG"
        elif row.get("ema_fast") < row.get("ema_slow"):
            side = "SHORT"

        if not side:
            _log("no_signal", symbol=symbol)
            return

        # === חישוב SL/TP בסיסי (ATR ×1.5) ===
        atr = float(row.get("atr", 0)) or 0.005 * float(row["close"])
        entry = float(row["close"])
        if side == "LONG":
            sl = entry - atr * 1.5
            tp = entry + atr * 3
        else:
            sl = entry + atr * 1.5
            tp = entry - atr * 3

        # === ביצוע טרייד אמיתי ===
        trade_result: Dict[str, Any] = await binance_futures_trade(
            symbol=symbol,
            side=side,
            entry=entry,
            sl=sl,
            tp=tp,
            leverage=cfg.DEFAULT_LEVERAGE,
            budget=cfg.MAX_TRADE_BUDGET,
            margin_type="ISOLATED",
            cid_prefix="autoexec"
        )

        # === שמירה להיסטוריה ===
        trade_record = {
            "symbol": symbol,
            "side": side,
            "entry": entry,
            "sl": sl,
            "tp": tp,
            "budget": cfg.MAX_TRADE_BUDGET,
            "leverage": cfg.DEFAULT_LEVERAGE,
            "resp": trade_result,
            "ts": time.time(),
        }
        EXECUTOR_TRADES.append(trade_record)
        _log("trade_executed", symbol=symbol, side=side, entry=entry, sl=sl, tp=tp)

    except Exception as e:
        _log("scan_error", symbol=symbol, level="ERROR", error=str(e))


# ---------------------------------------------------
# Executor loop
# ---------------------------------------------------
async def auto_scan_and_trade():
    global EXECUTOR_RUNNING, EXECUTOR_SYMBOLS, EXECUTOR_LAST_TS
    EXECUTOR_RUNNING = True
    try:
        while EXECUTOR_RUNNING:
            EXECUTOR_LAST_TS = time.time()   # ⏱️ מתעדכן כל מחזור
            EXECUTOR_SYMBOLS = [s.upper() for s in cfg.WATCHLIST]
            if "BTCUSDT" not in EXECUTOR_SYMBOLS:
                EXECUTOR_SYMBOLS.insert(0, "BTCUSDT")

            for symbol in EXECUTOR_SYMBOLS:
                await scan_and_trade(symbol)

            await asyncio.sleep(cfg.SCAN_INTERVAL)
    finally:
        EXECUTOR_RUNNING = False
        EXECUTOR_SYMBOLS = []
        EXECUTOR_LAST_TS = None
        _log("executor_stopped", level="INFO")


def start_executor():
    global EXECUTOR_RUNNING
    if EXECUTOR_RUNNING:
        _log("executor_already_running")
        return

    _log("executor_starting")
    loop = asyncio.get_event_loop()
    if not loop.is_running():
        loop.run_until_complete(auto_scan_and_trade())
    else:
        loop.create_task(auto_scan_and_trade())


def stop_executor():
    global EXECUTOR_RUNNING
    if EXECUTOR_RUNNING:
        EXECUTOR_RUNNING = False
        _log("executor_stopping")
    else:
        _log("executor_not_running")
















































































