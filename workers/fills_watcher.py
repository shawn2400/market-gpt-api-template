# workers/fills_watcher.py
from __future__ import annotations
import os
import time
import logging
import threading
import asyncio
from typing import Dict, Any, Optional, List, Tuple

from utils.metrics_prom import inc_fill, set_rr, inc_profit_lock, observe_ttp1
from utils.rr import rr_now

log = logging.getLogger("algogpt.fills_watcher")

# Import trade manager for dynamic SL/TP/BE management
try:
    from utils.trade_manager import manage_open_trades
except Exception:
    async def manage_open_trades():  # type: ignore
        log.debug("trade_manager unavailable")
        pass

# ייבוא עדין של לקוח הבורסה
try:
    from utils.binance_client import get_price, get_position_info
except Exception:
    def get_price(symbol: str) -> Optional[float]:
        return None
    def get_position_info(symbol: str) -> Dict[str, Any]:
        # צורת מפתח נפוצה: {"entryPrice": "..., "positionAmt": "...", "updateTime": 123...}
        return {}

# פרמטרים
ENABLED = (os.getenv("FILLS_WATCH_ENABLE", "1").lower() in ("1", "true", "yes", "on"))
INTERVAL = int(os.getenv("FILLS_WATCH_INTERVAL_SEC", "15"))
WATCHLIST = [s.strip().upper() for s in (os.getenv("FILLS_WATCHLIST", os.getenv("WATCHLIST", "")) or "").split(",") if s.strip()]

# Note: BE/Lock functionality moved to trade_manager.py
# fills_watcher focuses on monitoring and metrics only

# זמן כניסה → למדוד time_to_tp1 (בפשטות נאתחל כשיש פוזיציה פעילה)
_entry_ts: Dict[str, float] = {}
_tp1_done: Dict[str, bool] = {}
_last_manage_ts: float = 0.0  # Track last time we called manage_open_trades

def _position_snapshot(symbol: str) -> Tuple[Optional[float], Optional[float]]:
    """
    מחזיר (entry_price, qty_abs) אם יש פוזיציה, אחרת (None, None)
    """
    try:
        info = get_position_info(symbol) or {}
        ep = float(info.get("entryPrice") or 0.0)
        amt = abs(float(info.get("positionAmt") or 0.0))
        if ep > 0 and amt > 0:
            return ep, amt
    except Exception as e:
        log.debug("position_info_failed %s: %s", symbol, e)
    return None, None


def _tick_symbol(symbol: str):
    # בדיקת פוזיציה
    ep, qty = _position_snapshot(symbol)
    now = time.time()

    if ep and qty and symbol not in _entry_ts:
        _entry_ts[symbol] = now
        _tp1_done[symbol] = False

    if not (ep and qty):
        # אין פוזיציה → איפוס
        _entry_ts.pop(symbol, None)
        _tp1_done.pop(symbol, None)
        return

    # חישוב RR ועידכון Gauge
    try:
        current = float(get_price(symbol) or 0.0)
        if current > 0:
            # אין לנו SL/TP כאן; אם יש לך חנות תכניות – אפשר לשאוב ממנה. נשתמש בקירובים:
            sl = ep * 0.985  # 1.5% SL דיפולטי רזה
            tp1 = ep * 1.018  # 1.8% TP1 דיפולטי רזה
            rr = rr_now("BUY" if current >= ep else "SELL", entry=ep, sl=sl, tp=tp1, current=current)
            if rr is not None:
                set_rr(symbol, rr)

            # TP1?
            if not _tp1_done.get(symbol) and ((current >= tp1 and current >= ep) or (current <= tp1 and current <= ep)):
                _tp1_done[symbol] = True
                inc_fill(symbol, "tp1")
                if symbol in _entry_ts:
                    observe_ttp1(now - _entry_ts[symbol])

    except Exception as e:
        log.debug("tick_symbol_failed %s: %s", symbol, e)


class _TradeManagerThread(threading.Thread):
    """Dedicated thread for dynamic SL/TP/BE/Trailing management - runs every 60s"""
    daemon = True

    def run(self):
        log.info("[TradeManagerThread] Started - will manage open trades every 60s")
        while True:
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(manage_open_trades())
                loop.close()
            except Exception as e:
                log.debug("[TradeManagerThread] manage_open_trades failed: %s", e)
            time.sleep(60)


class _Worker(threading.Thread):
    daemon = True
    def run(self):
        # Start dedicated trade manager thread (independent of WATCHLIST)
        mgmt = _TradeManagerThread()
        mgmt.start()
        log.info("[fills_watcher] Trade manager thread started")

        if not WATCHLIST:
            log.warning("[fills_watcher] WATCHLIST empty; set FILLS_WATCHLIST or WATCHLIST")
        while True:
            if not ENABLED:
                time.sleep(INTERVAL)
                continue
            for sym in WATCHLIST:
                try:
                    _tick_symbol(sym)
                except Exception as e:
                    log.debug("watcher_error %s: %s", sym, e)
            time.sleep(INTERVAL)


_worker: Optional[_Worker] = None

def start():
    global _worker
    if _worker is None:
        _worker = _Worker()
        _worker.start()
        log.info("[fills_watcher] started (interval=%ss, enabled=%s, watch=%s)", INTERVAL, ENABLED, WATCHLIST)

if __name__ == "__main__":
    print("⚡ [fills_watcher] __main__ entry - starting worker...")
    start()
    print("⚡ [fills_watcher] Worker started successfully")
    # Keep process alive - daemon thread needs main thread running
    while True:
        time.sleep(60)
