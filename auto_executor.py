import os
import asyncio
import logging
from dotenv import load_dotenv
from utils.watchlist_utils import load_watchlist
from utils.multi_tf_scanner import multi_tf_scan_with_ai
from utils.trade_executor import execute_trade_live
from utils.ai_analysis import predict_optimal_sl_tp
from utils.ws_fallback import get_price, is_price_fresh

load_dotenv()

SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", 60))
MIN_QUALITY_SCORE = int(os.getenv("MIN_QUALITY_SCORE", 6))
MAX_TRADE_BUDGET = float(os.getenv("MAX_TRADE_BUDGET", 100))

_running = False
_task = None

async def executor_loop():
    global _running
    _running = True
    logging.info("[AUTO] Auto Executor started")

    try:
        while _running:
            try:
                watchlist = load_watchlist(min_quality=MIN_QUALITY_SCORE)
                logging.info(f"[AUTO] Loaded watchlist type: {type(watchlist)}, length: {len(watchlist)}")

                symbols = []
                for i, entry in enumerate(watchlist):
                    logging.debug(f"[AUTO] Watchlist entry {i} type: {type(entry)}, content: {entry}")
                    if not isinstance(entry, dict):
                        logging.error(f"[AUTO] Invalid watchlist entry at index {i}: not a dict")
                        continue
                    if "symbol" not in entry:
                        logging.error(f"[AUTO] Watchlist entry at index {i} missing 'symbol' key")
                        continue
                    symbols.append(entry["symbol"])

                if not symbols:
                    logging.info("[AUTO] No symbols with sufficient quality found.")
                    await asyncio.sleep(SCAN_INTERVAL)
                    continue

                logging.info(f"[AUTO] Scanning {len(symbols)} symbols...")

                scan_results = await multi_tf_scan_with_ai(
                    timeframes=("15m", "1h"),
                    markets=("futures",),
                    min_quality=MIN_QUALITY_SCORE,
                    top=5,
                    trending_only=False
                )

                for trade in scan_results:
                    # ודא ש-trade הוא dict ושיש מפתח symbol
                    if not isinstance(trade, dict):
                        logging.error(f"[AUTO] Invalid trade item (not dict): {trade}")
                        continue
                    if "symbol" not in trade:
                        logging.error(f"[AUTO] Trade missing 'symbol': {trade}")
                        continue

                    symbol = trade["symbol"]
                    direction = trade.get("direction", trade.get("main_direction", "LONG")).upper()

                    entry = await get_price(symbol)
                    if not entry:
                        logging.warning(f"[AUTO] Price not available for {symbol}, skipping.")
                        continue

                    if not is_price_fresh(symbol, max_age_sec=10):
                        logging.warning(f"[AUTO] Price stale for {symbol}, skipping.")
                        continue

                    sl_tp = await predict_optimal_sl_tp(symbol, direction, entry)
                    if isinstance(sl_tp, dict) and "error" in sl_tp:
                        logging.warning(f"[AUTO] SL/TP prediction failed for {symbol}: {sl_tp['error']}")
                        continue

                    stop, tp = sl_tp if isinstance(sl_tp, tuple) else (None, None)
                    if stop is None or tp is None:
                        logging.warning(f"[AUTO] Invalid SL/TP for {symbol}, skipping.")
                        continue

                    logging.info(f"[AUTO] Trade recommended: {symbol} | {direction} | Entry: {entry} | SL: {stop} | TP: {tp}")

                    result = await execute_trade_live(
                        symbol=symbol,
                        entry=entry,
                        stop=stop,
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
        logging.info("[AUTO] Executor stopped")

def start_executor():
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(executor_loop())
        logging.info("[AUTO] Executor started")
        return True
    else:
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
    else:
        logging.info("[AUTO] Executor was not running")
        return False

def is_executor_running():
    return _running




































































