# workers/fills_watcher.py
from __future__ import annotations
import os
import time
import logging
import threading
from typing import Dict, Any, Optional, List, Tuple

from utils.metrics_prom import inc_fill, set_rr, inc_profit_lock, observe_ttp1
from utils.rr import rr_now

log = logging.getLogger("algogpt.fills_watcher")

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

# BE/Lock
from utils.tp_helper import be_stair_and_profit_lock

# זמן כניסה → למדוד time_to_tp1 (בפשטות נאתחל כשיש פוזיציה פעילה)
_entry_ts: Dict[str, float] = {}
_tp1_done: Dict[str, bool] = {}

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

            # Profit-Lock קליל (בהתבסס על RR)
            if rr is not None:
                resp = be_stair_and_profit_lock(symbol, rr=rr, adx=22.0, atr_pct=1.0)
                if resp.get("ok") and not resp.get("skipped"):
                    inc_profit_lock(symbol, "be_or_lock")
    except Exception as e:
        log.debug("tick_symbol_failed %s: %s", symbol, e)


class _Worker(threading.Thread):
    daemon = True
    def run(self):
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
