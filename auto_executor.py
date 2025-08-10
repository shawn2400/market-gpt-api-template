# auto_executor.py
import asyncio
import logging

from utils import config
from utils.watchlist_utils import load_watchlist
from utils.multi_tf_scanner import multi_tf_scan_with_ai
from utils.trade_executor import execute_trade_live
from utils.ai_analysis import predict_optimal_sl_tp
from utils.ws_fallback import get_price, is_price_fresh

SCAN_INTERVAL = int(config.SCAN_INTERVAL)
MIN_QUALITY_SCORE = int(config.MIN_QUALITY_SCORE)
MAX_TRADE_BUDGET = float(config.MAX_TRADE_BUDGET)
PRICE_MAX_AGE_SEC = int(config.PRICE_MAX_AGE_SEC)

_running = False
_task: asyncio.Task | None = None

async def executor_loop():
    """
    לולאת אוטו-אקסקיוטר מחושלת:
    - קוראת watchlist בבטחה
    - מריצה multi_tf_scan_with_ai
    - מאמתת price & SL/TP
    - מבצעת טריידים בפועל עם execute_trade_live
    """
    global _running
    _running = True
    logging.info("[AUTO] Auto Executor started")

    try:
        while _running:
            try:
                watchlist = load_watchlist(min_quality=MIN_QUALITY_SCORE)
                if not isinstance(watchlist, list):
                    logging.error(f"[AUTO] watchlist is not a list: {type(watchlist)} content: {watchlist}")
                    watchlist = []

                symbols = []
                for entry in watchlist:
                    if not isinstance(entry, dict):
                        logging.error(f"[AUTO] watchlist entry not dict: {type(entry)} content: {entry}")
                        continue
                    if "symbol" not in entry:
                        logging.error(f"[AUTO] watchlist entry missing 'symbol': {entry}")
                        continue
                    symbols.append(str(entry["symbol"]).upper())

                # סריקה (גם אם אין רשימה – הסורק יודע להביא trending/fallback)
                logging.info(f"[AUTO] Scanning (min_quality={MIN_QUALITY_SCORE})…")
                scan_results = await multi_tf_scan_with_ai(
                    timeframes=("15m", "1h"),
                    markets=("futures",),
                    min_quality=MIN_QUALITY_SCORE,
                    top=min(5, config.TOP_SYMBOLS),
                    trending_only=config.TRENDING_ONLY,
                    symbols=symbols or None
                )

                for trade in scan_results:
                    if not isinstance(trade, dict) or "symbol" not in trade:
                        logging.error(f"[AUTO] invalid scan result item: {trade}")
                        continue

                    symbol = str(trade["symbol"]).upper()
                    direction = str(trade.get("direction", trade.get("main_direction", "LONG"))).upper()
                    direction = "LONG" if direction not in ("LONG", "SHORT") else direction

                    entry_price = await get_price(symbol)
                    if entry_price is None:
                        logging.warning(f"[AUTO] Price not available for {symbol}, skipping.")
                        continue

                    if not is_price_fresh(symbol, max_age_sec=PRICE_MAX_AGE_SEC):
                        logging.warning(f"[AUTO] Price stale for {symbol}, skipping.")
                        continue

                    sl, tp = await predict_optimal_sl_tp(symbol, direction, entry_price)
                    if sl is None or tp is None:
                        logging.warning(f"[AUTO] Invalid SL/TP for {symbol}, skipping.")
                        continue

                    logging.info(
                        f"[AUTO] Trade candidate: {symbol} | {direction} | Entry: {entry_price} | SL: {sl} | TP: {tp}"
                    )

                    result = await execute_trade_live(
                        symbol=symbol,
                        entry=entry_price,
                        stop=sl,
                        tp=tp,
                        direction=direction,
                        leverage=20,
                        budget_usd=MAX_TRADE_BUDGET,
                        market_type="futures"
                    )
                    logging.info(f"[AUTO] Trade result: {result}")

            except asyncio.CancelledError:
                logging.info("[AUTO] Executor cancelled")
                break
            except Exception as e:
                logging.error(f"[AUTO] Loop error: {e}", exc_info=True)

            await asyncio.sleep(SCAN_INTERVAL)
    finally:
        _running = False
        logging.info("[AUTO] Auto Executor stopped")

def start_executor():
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(executor_loop())
        logging.info("[AUTO] Executor started")
        return True
    logging.info("[AUTO] Executor already running")
    return False

def stop_executor():
    global _running, _task
    if _running:
        _running = False
        if _task:
            _task.cancel()
            _task = None
        logging.info("[AUTO] Executor stopped")
        return True
    logging.info("[AUTO] Executor was not running")
    return False

def is_executor_running():
    return _running






































































