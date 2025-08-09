# auto_executor.py

import os
import asyncio
import logging
from dotenv import load_dotenv

from utils.watchlist_utils import get_symbols_list
from utils.multi_tf_scanner import multi_tf_scan_with_ai
from utils.trade_executor import execute_trade_live
from utils.ai_analysis import predict_optimal_sl_tp
from utils.ws_fallback import get_price, is_price_fresh

load_dotenv()

SCAN_INTERVAL = max(5, int(os.getenv("SCAN_INTERVAL", 60)))          # רצפה ל-5 שניות
MIN_QUALITY_SCORE = int(os.getenv("MIN_QUALITY_SCORE", 6))
MAX_TRADE_BUDGET = float(os.getenv("MAX_TRADE_BUDGET", 100))
DEFAULT_LEVERAGE = int(os.getenv("DEFAULT_LEVERAGE", 25))            # ברירת מחדל 25
PRICE_MAX_AGE_SEC = int(os.getenv("PRICE_MAX_AGE_SEC", 10))

_running = False
_task: asyncio.Task | None = None


async def _handle_trade_candidate(trade: dict) -> None:
    """
    מטפל במועמד יחיד מהסריקה:
    חישוב Entry חי, אימות טריות מחיר, חיזוי SL/TP, וביצוע טרייד חי.
    הגנות מלאות לשדות חסרים/סוגים לא צפויים.
    """
    try:
        if not isinstance(trade, dict):
            logging.error(f"[AUTO] scan result item not dict: {type(trade)} content: {repr(trade)[:200]}")
            return

        symbol = str(trade.get("symbol", "")).strip().upper()
        if not symbol:
            logging.error(f"[AUTO] scan result missing symbol: {repr(trade)[:200]}")
            return

        # כיוון: נסה מספר שדות, ברירת מחדל LONG
        d = trade.get("direction") or trade.get("main_direction") or "LONG"
        direction = str(d).strip().upper()
        if direction not in ("LONG", "SHORT"):
            # אם יש trend/supertrend_dir – ננסה לנרמל, אחרת LONG
            stdir = trade.get("supertrend_dir") or trade.get("trend")
            try:
                stdir = int(stdir)
                direction = "LONG" if stdir == 1 else "SHORT"
            except Exception:
                direction = "LONG"

        # שלוף מחיר חי + בדיקת טריות
        entry = await get_price(symbol)
        if entry is None:
            logging.warning(f"[AUTO] Price not available for {symbol}, skipping.")
            return

        if not await asyncio.to_thread(is_price_fresh, symbol, PRICE_MAX_AGE_SEC):
            logging.warning(f"[AUTO] Price stale for {symbol}, skipping.")
            return

        # חיזוי SL/TP (tuple)
        sl_tp = await predict_optimal_sl_tp(symbol, direction, entry)
        if isinstance(sl_tp, dict) and "error" in sl_tp:
            logging.warning(f"[AUTO] SL/TP prediction failed for {symbol}: {sl_tp.get('error')}")
            return

        try:
            stop, tp = sl_tp if isinstance(sl_tp, tuple) else (None, None)
        except Exception:
            stop, tp = (None, None)

        if stop is None or tp is None:
            logging.warning(f"[AUTO] Invalid SL/TP for {symbol}, skipping.")
            return

        logging.info(f"[AUTO] Trade candidate ✅ {symbol} | {direction} | Entry={entry} | SL={stop} | TP={tp} | Lev={DEFAULT_LEVERAGE} | Budget=${MAX_TRADE_BUDGET}")

        # ביצוע טרייד חי
        result = await execute_trade_live(
            symbol=symbol,
            entry=entry,
            stop=stop,
            tp=tp,
            direction=direction,
            leverage=DEFAULT_LEVERAGE,
            budget_usd=MAX_TRADE_BUDGET,
            market_type="futures"
        )
        logging.info(f"[AUTO] Trade result: {result}")

    except asyncio.CancelledError:
        raise
    except Exception as e:
        logging.error(f"[AUTO] handle_trade_candidate error: {e}", exc_info=True)


async def executor_loop():
    """
    לולאת האוטו-אקסקיוטר:
    - טוענת רשימת סמלים (מנורמלת) מעל סף איכות
    - מריצה סריקת Multi-TF עם AI
    - מטפלת בכל מועמד טרייד שנמצא
    """
    global _running
    _running = True
    logging.info("[AUTO] Auto Executor started")

    try:
        while _running:
            try:
                # טען סמלים בלבד — נמנע מבאגי dict מול string
                symbols = get_symbols_list(min_quality=MIN_QUALITY_SCORE)

                if not symbols:
                    logging.info("[AUTO] No symbols with sufficient quality found. Sleeping…")
                    await asyncio.sleep(SCAN_INTERVAL)
                    continue

                logging.info(f"[AUTO] Scanning {len(symbols)} symbols…")

                # חשוב: אם multi_tf_scan_with_ai תומך ב- symbols=, נעביר; אחרת היא תשתמש ב-watchlist פנימית.
                try:
                    scan_results = await multi_tf_scan_with_ai(
                        timeframes=("15m", "1h"),
                        markets=("futures",),
                        min_quality=MIN_QUALITY_SCORE,
                        top=5,
                        trending_only=False,
                        symbols=symbols  # אם הפונקציה שלך לא מקבלת פרמטר זה – הסר שורה זו
                    )
                except TypeError:
                    # תאימות לאחור: חתימה ללא symbols
                    scan_results = await multi_tf_scan_with_ai(
                        timeframes=("15m", "1h"),
                        markets=("futures",),
                        min_quality=MIN_QUALITY_SCORE,
                        top=5,
                        trending_only=False
                    )

                if not isinstance(scan_results, list):
                    logging.error(f"[AUTO] scan_results is not a list: {type(scan_results)} content: {repr(scan_results)[:200]}")
                    await asyncio.sleep(SCAN_INTERVAL)
                    continue

                if not scan_results:
                    logging.info("[AUTO] No trade candidates found in this iteration.")
                    await asyncio.sleep(SCAN_INTERVAL)
                    continue

                # טיפול סידרתי במועמדים (ניתן לשדרג ל-gather עם הגבלת מקביליות אם תרצה)
                for trade in scan_results:
                    await _handle_trade_candidate(trade)

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





































































