# auto_executor.py
import asyncio
import logging
import time
from typing import Optional, List, Dict, Set, Tuple

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
        # ספים חדשים (ניתן לשנות בקובץ config)
        SL_MIN_PCT = 0.20
        SL_MAX_PCT = 5.00
        TP_MIN_PCT = 0.30
        TP_MAX_PCT = 8.00
        SYMBOL_COOLDOWN_SEC = 600
        MAX_TRADES_PER_TICK = 3
    config = _Dummy()

_SCAN_INTERVAL = int(getattr(config, "SCAN_INTERVAL", 60))
_AUTO_RUN_BOOT = bool(getattr(config, "AUTO_RUN", False))

_ENABLE_REAL_SCANNER = bool(getattr(config, "ENABLE_AUTO_TRADING", False))
_EXECUTE_TRADES      = bool(getattr(config, "EXECUTE_TRADES", False))
_MIN_Q               = float(getattr(config, "MIN_QUALITY_SCORE", 6))
_BUDGET              = float(getattr(config, "MAX_TRADE_BUDGET", 100.0))
_TRENDING_ONLY       = bool(getattr(config, "TRENDING_ONLY", True))

# ספים ל-SL/TP (% מהמחיר החי)
_SL_MIN_PCT = float(getattr(config, "SL_MIN_PCT", 0.20))  # 0.20%
_SL_MAX_PCT = float(getattr(config, "SL_MAX_PCT", 5.00))  # 5.00%
_TP_MIN_PCT = float(getattr(config, "TP_MIN_PCT", 0.30))  # 0.30%
_TP_MAX_PCT = float(getattr(config, "TP_MAX_PCT", 8.00))  # 8.00%

# קירור פר-סימבול (בשניות)
_SYMBOL_COOLDOWN_SEC = int(getattr(config, "SYMBOL_COOLDOWN_SEC", 600))
_MAX_TRADES_PER_TICK = int(getattr(config, "MAX_TRADES_PER_TICK", 3))

_task: Optional[asyncio.Task] = None
_stop_evt: Optional[asyncio.Event] = None

# זיכרון זמני למניעת טריידים תכופים מדי על אותו סימבול
_last_trade_time: Dict[str, float] = {}


async def _get_mark_price(symbol: str) -> Optional[float]:
    """
    שליפת Mark Price בטוחה. מחזיר float או None.
    """
    try:
        from utils.binance_client import futures_mark_price
        data = await asyncio.to_thread(futures_mark_price, symbol)
        if isinstance(data, dict):
            for key in ("markPrice", "price", "indexPrice", "estimatedSettlePrice"):
                v = data.get(key)
                if v is None:
                    continue
                try:
                    p = float(v)
                    if p > 0:
                        return p
                except Exception:
                    continue
        logging.warning("[AUTO] mark price parse failed for %s: %s", symbol, data)
    except Exception as e:
        logging.warning("[AUTO] mark price fetch failed for %s: %s", symbol, e)
    return None


def _pick_atr(details: List[Dict]) -> Optional[float]:
    """
    מנסה לאסוף ATR עדכני מרשימת פריימים שחושבו בסריקה.
    """
    for d in details or []:
        try:
            atr = d.get("atr")
            if atr is None:
                atr = (d.get("indicators") or {}).get("atr")
            if atr is not None:
                atr_f = float(atr)
                if atr_f > 0:
                    return atr_f
        except Exception:
            continue
    return None


def _pct_distance_long(entry: float, sl: float, tp: float) -> Tuple[float, float]:
    sl_pct = max(0.0, (entry - sl) / entry * 100.0)
    tp_pct = max(0.0, (tp - entry) / entry * 100.0)
    return sl_pct, tp_pct


def _pct_distance_short(entry: float, sl: float, tp: float) -> Tuple[float, float]:
    sl_pct = max(0.0, (sl - entry) / entry * 100.0)
    tp_pct = max(0.0, (entry - tp) / entry * 100.0)
    return sl_pct, tp_pct


def _valid_sl_tp(entry: float, sl: float, tp: float, direction: str) -> bool:
    """
    בודק שה-SL/TP תואמים את הכיוון ושמרחקי האחוזים בתחום המותר.
    """
    if entry <= 0 or sl <= 0 or tp <= 0:
        return False

    d = direction.upper()
    if d == "LONG":
        if not (sl <= entry and tp >= entry):
            return False
        sl_pct, tp_pct = _pct_distance_long(entry, sl, tp)
    elif d == "SHORT":
        if not (sl >= entry and tp <= entry):
            return False
        sl_pct, tp_pct = _pct_distance_short(entry, sl, tp)
    else:
        return False

    # בדיקת טווחים
    if not (_SL_MIN_PCT <= sl_pct <= _SL_MAX_PCT):
        logging.info("[AUTO] SL pct out of bounds (%.3f%% not in [%.3f%%, %.3f%%])",
                     sl_pct, _SL_MIN_PCT, _SL_MAX_PCT)
        return False
    if not (_TP_MIN_PCT <= tp_pct <= _TP_MAX_PCT):
        logging.info("[AUTO] TP pct out of bounds (%.3f%% not in [%.3f%%, %.3f%%])",
                     tp_pct, _TP_MIN_PCT, _TP_MAX_PCT)
        return False

    return True


def _cooldown_ok(symbol: str) -> bool:
    """
    בודק האם עבר מספיק זמן מאז הטרייד האחרון על הסימבול.
    """
    if _SYMBOL_COOLDOWN_SEC <= 0:
        return True
    now = time.time()
    last = _last_trade_time.get(symbol)
    if last is None or (now - last) >= _SYMBOL_COOLDOWN_SEC:
        return True
    left = int(_SYMBOL_COOLDOWN_SEC - (now - last))
    logging.info("[AUTO] cooldown active for %s: %ss left", symbol, left)
    return False


def _touch_cooldown(symbol: str) -> None:
    _last_trade_time[symbol] = time.time()


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

    # 2) אם לא מבצעים טריידים בפועל — רק דווח
    if not _EXECUTE_TRADES:
        logging.info(
            "[AUTO] scan only (EXECUTE_TRADES=false) — total=%s; top=%s",
            len(results), results[0].get("symbol"),
        )
        return

    # 3) בחירה זהירה: BUY/SELL ואיכות ≥ סף
    picked = [
        r for r in results
        if str(r.get("signal", "HOLD")).upper() in ("BUY", "SELL")
        and float(r.get("quality_score", 0)) >= _MIN_Q
    ]
    if not picked:
        logging.info("[AUTO] no signals above threshold (q>=%.2f)", _MIN_Q)
        return

    placed: int = 0
    used_symbols: Set[str] = set()

    for r in picked:
        if placed >= _MAX_TRADES_PER_TICK:
            break

        sym = str(r.get("symbol", "")).upper().strip()
        if not sym or sym in used_symbols:
            continue

        if not _cooldown_ok(sym):
            continue

        side = str(r.get("signal", "HOLD")).upper()
        direction = "LONG" if side == "BUY" else "SHORT"

        details = r.get("details") or []
        atr = _pick_atr(details)

        entry_price = await _get_mark_price(sym)
        if not entry_price or entry_price <= 0:
            logging.warning("[AUTO] skip %s — no live price", sym)
            continue

        # חישוב SL/TP
        try:
            from utils.ai_analysis import predict_optimal_sl_tp
            sl, tp = await predict_optimal_sl_tp(sym, direction, entry_price=entry_price, atr=atr)
        except Exception as e:
            logging.warning("[AUTO] cannot compute SL/TP for %s: %s — skipping", sym, e)
            continue

        if not _valid_sl_tp(entry_price, sl, tp, direction):
            logging.info("[AUTO] skip %s — SL/TP not within bounds | entry=%.6f sl=%.6f tp=%.6f",
                         sym, entry_price, sl, tp)
            continue

        # 4) ביצוע — execute_trade_live יעשה ולידציות נוספות
        try:
            resp = await execute_trade_live(
                symbol=sym,
                entry=None,           # קח מחיר חי בתוך הפונקציה
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
                logging.info("[AUTO] trade placed %s %s | entry≈%.6f sl=%.6f tp=%.6f q=%.2f",
                             direction, sym, entry_price, sl, tp, float(r.get("quality_score", 0)))
                placed += 1
                used_symbols.add(sym)
                _touch_cooldown(sym)
        except Exception as e:
            logging.error("[AUTO] trade exception for %s: %s", sym, e)

    if placed == 0:
        logging.info("[AUTO] no trades placed this tick")


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











































































