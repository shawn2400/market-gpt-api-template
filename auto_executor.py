# auto_executor.py
import asyncio
import logging
from typing import Optional, List

from utils import config
from utils.watchlist_utils import load_watchlist, get_symbols_list
from utils.multi_tf_scanner import multi_tf_scan_with_ai
from utils.trade_executor import execute_trade_live
from utils.ai_analysis import predict_optimal_sl_tp
from utils.ws_fallback import get_price, is_price_fresh, launch_multi_websocket

SCAN_INTERVAL        = max(5, int(getattr(config, "SCAN_INTERVAL", 60)))  # נימוס לרשת
MIN_QUALITY_SCORE    = int(getattr(config, "MIN_QUALITY_SCORE", 6))
MAX_TRADE_BUDGET     = float(getattr(config, "MAX_TRADE_BUDGET", 100.0))
PRICE_MAX_AGE_SEC    = int(getattr(config, "PRICE_MAX_AGE_SEC", 10))

# מצב "יבש": לא מבצע פקודות חתומות לבייננס (לניטור/דמו/בדיקות)
SKIP_MUTATIONS = bool(
    getattr(config, "BINANCE_SKIP_MUTATIONS", False) or
    getattr(config, "SKIP_BINANCE_MUTATIONS", False)
)

_running = False
_task: Optional[asyncio.Task] = None


async def _init_ws_symbols() -> List[str]:
    """
    בונה סט סמלים להפעלת WebSocket בתחילת הריצה.
    אם אין ב-watchlist, יופעל fallback קטן.
    """
    try:
        syms = get_symbols_list(min_quality=MIN_QUALITY_SCORE)
        if not syms:
            # fallback מינימלי כדי שתהיה תנועת מחירים
            syms = ["BTCUSDT", "ETHUSDT", "BNBUSDT"]
        # ייחוד וסידור
        out = sorted({s.upper() for s in syms if s})
        return out
    except Exception as e:
        logging.warning(f"[AUTO] WS symbol init failed: {e}")
        return ["BTCUSDT", "ETHUSDT", "BNBUSDT"]


async def executor_loop():
    """
    לולאת Auto-Executor:
    - מפעילה WS למחירים
    - טוענת watchlist
    - מריצה multi_tf_scan_with_ai
    - מאמתת מחיר / טריות / SL-TP
    - מבצעת טרייד עם הגנות (price deviation guard)
    - מכבדת מצב 'יבש' (SKIP_MUTATIONS) לביצוע ללא שליחת הזמנות
    """
    global _running
    _running = True
    logging.info("[AUTO] Auto Executor started (skip_mutations=%s)", SKIP_MUTATIONS)

    # === הפעלת WS פעם אחת בתחילת הריצה ===
    try:
        ws_syms = await _init_ws_symbols()
        await launch_multi_websocket(ws_syms)
        logging.info(f"[AUTO] WS launched for {len(ws_syms)} symbols")
    except Exception as e:
        logging.warning(f"[AUTO] WS launch warning: {e}")

    try:
        # לולאת סריקה אינסופית (עד stop)
        while _running:
            try:
                # --- בניית רשימת סמלים מתוך watchlist (אופציונלי) ---
                watchlist = load_watchlist(min_quality=MIN_QUALITY_SCORE)
                symbols: List[str] = []
                for entry in watchlist:
                    if isinstance(entry, dict) and entry.get("symbol"):
                        symbols.append(str(entry["symbol"]).upper())

                logging.info(f"[AUTO] Scanning (min_quality={MIN_QUALITY_SCORE})…")
                scan_results = await multi_tf_scan_with_ai(
                    timeframes=("15m", "1h"),
                    markets=("futures",),
                    min_quality=MIN_QUALITY_SCORE,
                    top=min(5, int(getattr(config, "TOP_SYMBOLS", 30))),
                    trending_only=bool(getattr(config, "TRENDING_ONLY", True)),
                    symbols=symbols or None
                )

                # נרווח מעט בין מועמדים כדי להפחית 403/WAF כשיש כמה פעולות רצוף
                for idx, trade in enumerate(scan_results):
                    if not isinstance(trade, dict) or "symbol" not in trade:
                        logging.error(f"[AUTO] invalid scan result item: {trade}")
                        continue

                    symbol = str(trade["symbol"]).upper()
                    direction = str(trade.get("direction", trade.get("main_direction", "LONG"))).upper()
                    direction = direction if direction in ("LONG", "SHORT") else "LONG"

                    # מחיר נוכחי
                    entry_price = await get_price(symbol)
                    if entry_price is None:
                        logging.warning(f"[AUTO] Price not available for {symbol}, skipping.")
                        continue
                    if not is_price_fresh(symbol, max_age_sec=PRICE_MAX_AGE_SEC):
                        logging.warning(f"[AUTO] Price stale for {symbol}, skipping.")
                        continue

                    # חישוב SL/TP (עם AI או fallback)
                    try:
                        sl, tp = await predict_optimal_sl_tp(symbol, direction, float(entry_price))
                    except Exception as e:
                        logging.warning(f"[AUTO] SL/TP calc failed for {symbol}: {e}")
                        continue

                    if sl is None or tp is None:
                        logging.warning(f"[AUTO] Invalid SL/TP for {symbol}, skipping.")
                        continue

                    logging.info(
                        f"[AUTO] Trade candidate: {symbol} | {direction} | Entry: {entry_price} | SL: {sl} | TP: {tp}"
                    )

                    if SKIP_MUTATIONS:
                        # מצב יבשות: לא נוגעים בחשבון בבייננס
                        logging.info(f"[AUTO] SKIP_MUTATIONS=on → not placing real order for {symbol}")
                    else:
                        # jitter קצר לפני ביצוע להזמנות חתומות
                        await asyncio.sleep(0.25)
                        result = await execute_trade_live(
                            symbol=symbol,
                            entry=float(entry_price),
                            stop=float(sl),
                            tp=float(tp),
                            direction=direction,
                            leverage=20,
                            budget_usd=MAX_TRADE_BUDGET,
                            market_type="futures"
                        )
                        logging.info(f"[AUTO] Trade result: {result}")

                    # רווח קטן גם בין מועמד למועמד
                    if idx < len(scan_results) - 1:
                        await asyncio.sleep(0.35)

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








































































