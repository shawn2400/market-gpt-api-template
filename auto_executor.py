# auto_executor.py
import asyncio
import logging
from typing import Optional, List, Dict

# קונפיג
try:
    from utils import config
except Exception:
    class _Dummy:
        AUTO_RUN = False
        SCAN_INTERVAL = 60
        ENABLE_AUTO_TRADING = False
        EXECUTE_TRADES = False
        MIN_QUALITY_SCORE = 6
        MAX_TRADE_BUDGET = 100.0
        TRENDING_ONLY = True
        DEFAULT_INTERVAL = "15m"
    config = _Dummy()

_SCAN_INTERVAL = int(getattr(config, "SCAN_INTERVAL", 60))
_AUTO_RUN_BOOT = bool(getattr(config, "AUTO_RUN", False))

_ENABLE_REAL_SCANNER = bool(getattr(config, "ENABLE_AUTO_TRADING", False))
_EXECUTE_TRADES      = bool(getattr(config, "EXECUTE_TRADES", False))
_MIN_Q               = float(getattr(config, "MIN_QUALITY_SCORE", 6))
_BUDGET              = float(getattr(config, "MAX_TRADE_BUDGET", 100.0))
_TRENDING_ONLY       = bool(getattr(config, "TRENDING_ONLY", True))

_task: Optional[asyncio.Task] = None
_stop_evt: Optional[asyncio.Event] = None

async def _tick():
    """
    טיק יחיד של סריקה/ביצוע.
    """
    from utils.multi_tf_scanner import multi_tf_scan_with_ai
    from utils.trade_executor import execute_trade_live
    from utils import config as cfg

    # 1) סריקה
    results: List[Dict] = await multi_tf_scan_with_ai(
        timeframes=(cfg.DEFAULT_INTERVAL, "1h"),
        markets=("futures",),
        min_quality=_MIN_Q,
        top=10,
        trending_only=_TRENDING_ONLY,
        trending_source="binance24h",
    )

    if not results:
        logging.info("[AUTO] no candidates this tick")
        return

    # 2) סינון ראשוני: לא להמשיך אם לא מפעילים ביצוע
    if not _EXECUTE_TRADES:
        logging.info("[AUTO] scan only (EXECUTE_TRADES=false) — top=%s; first=%s",
                     len(results), results[0].get("symbol"))
        return

    # 3) בחירה וביצוע זהיר: קח רק אותות BUY/SELL, איכות ≥ סף
    picked = [r for r in results if str(r.get("signal","HOLD")).upper() in ("BUY","SELL")
              and float(r.get("quality_score", 0)) >= _MIN_Q]

    for r in picked[:3]:  # אל תתפרע — עד 3 טריידים לטיק
        sym = str(r.get("symbol")).upper()
        direction = "LONG" if r["signal"].upper() == "BUY" else "SHORT"

        # נדרש: חישוב SL/TP בטרם ביצוע (כאן נשען על ה-AI בפייפליין העליון שלך)
        # אם יש לך נתוני SL/TP מפורשים בפריטים — השתמש בהם. אחרת אל תבצע.
        details = r.get("details") or []
        sl = None; tp = None
        try:
            from utils.ai_analysis import predict_optimal_sl_tp
            # נשתמש במחיר חי בתוך execute_trade_live; כאן רק מבטיחים שיהיו ערכים
            sl, tp = await predict_optimal_sl_tp(sym, direction, entry_price=0.0)
        except Exception as e:
            logging.warning("[AUTO] cannot compute SL/TP for %s: %s — skipping", sym, e)
            continue

        # ביצוע — execute_trade_live עושה ולידציות טריות/סטיות/Mutations
        try:
            resp = await execute_trade_live(
                symbol=sym,
                entry=None,          # קח live
                stop=sl,
                tp=tp,
                direction=direction,
                leverage=20,
                budget_usd=_BUDGET,
                market_type="futures",
            )
            status = resp.get("status")
            if status != "success":
                logging.warning("[AUTO] trade rejected %s %s -> %s", direction, sym, resp)
            else:
                logging.info("[AUTO] trade placed %s %s -> ok", direction, sym)
        except Exception as e:
            logging.error("[AUTO] trade exception for %s: %s", sym, e)

async def _runner():
    global _stop_evt
    logging.info("[AUTO] runner start: interval=%ss enable_scanner=%s execute_trades=%s",
                 _SCAN_INTERVAL, _ENABLE_REAL_SCANNER, _EXECUTE_TRADES)

    # טעינת מודולים כבדה רק אם צריך
    if _ENABLE_REAL_SCANNER:
        try:
            import utils.multi_tf_scanner  # noqa
        except Exception as e:
            logging.warning("[AUTO] scanner import failed; NO-OP mode: %s", e)

    while _stop_evt and not _stop_evt.is_set():
        try:
            if _ENABLE_REAL_SCANNER:
                await _tick()
            else:
                logging.debug("[AUTO] tick (noop)")
        except Exception as e:
            logging.warning("[AUTO] tick error (ignored): %s", e)
        try:
            await asyncio.wait_for(_stop_evt.wait(), timeout=_SCAN_INTERVAL)
        except asyncio.TimeoutError:
            pass
        except Exception as e:
            logging.debug("[AUTO] wait error (ignored): %s", e)

    logging.info("[AUTO] runner stopped")

def is_executor_running() -> bool:
    return bool(_task and not _task.done())

def start_executor() -> bool:
    global _task, _stop_evt
    if _task and not _task.done():
        return True
    loop = asyncio.get_running_loop()
    _stop_evt = asyncio.Event()
    _task = loop.create_task(_runner())
    logging.info("[AUTO] executor started")
    return True

def stop_executor() -> bool:
    global _task, _stop_evt
    if _stop_evt and not _stop_evt.is_set():
        _stop_evt.set()
    if _task and _task.done():
        _task = None
    logging.info("[AUTO] executor stop requested")
    return True

if _AUTO_RUN_BOOT:
    try:
        logging.info("[AUTO] AUTO_RUN=true (startup will start executor)")
    except Exception:
        pass











































































