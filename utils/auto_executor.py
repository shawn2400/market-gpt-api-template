# utils/auto_executor.py
from __future__ import annotations
import asyncio, logging, os, time, random
from collections import deque
from typing import Optional, Dict, Any, List

import pandas as pd

from utils import config as cfg
from utils.indicators import prepare_indicators_for_backtest
from utils.get_klines import get_klines_sync
from utils.anchor import evaluate_anchor
from utils.trade_executor import execute_trade_live  # ✅ סינכרוני
from utils.watchlist_utils import load_watchlist_env_or_fallback

# NEW: counters exposure
try:
    from utils.runtime_counters import exec_on_tick_stop, exec_on_batch_timeout, exec_on_trade_sent, ops_tick_safe
except Exception:
    def exec_on_tick_stop(*a, **k): pass
    def exec_on_batch_timeout(*a, **k): pass
    def exec_on_trade_sent(*a, **k): pass
    def ops_tick_safe(): pass

# Risk Gate (אופציונלי)
try:
    from utils.risk_checker import pre_trade_risk_check, RISK_CHECK_ENABLE
except Exception:
    RISK_CHECK_ENABLE = False
    def pre_trade_risk_check(*args, **kwargs):  # type: ignore
        return {"ok": True, "score": 100.0, "reasons": ["risk_module_missing"], "metrics": {}}

# Notifications
try:
    from utils.telegram_notifier import notify_no_trades, notify_scan_error
except Exception:
    async def notify_no_trades(): return None
    async def notify_scan_error(reason: str): return None

# Circuit-breaker & Scheduler
try:
    from utils.http_client import circuit_breaker_open
except Exception:
    def circuit_breaker_open() -> bool:  # type: ignore
        return False

try:
    from utils.symbol_scheduler import SymbolScheduler
except Exception:
    class SymbolScheduler:  # fallback
        def __init__(self, symbols: List[str], batch_size: Optional[int] = None):
            self.syms = list(dict.fromkeys([s.upper() for s in symbols if s]))
            self.i = 0
            self.bs = int(os.getenv("SCAN_MAX_LIMIT", "10")) if batch_size is None else int(batch_size)
            self.bs = max(1, min(self.bs, max(1, len(self.syms))))
        def next_batch(self) -> List[str]:
            if not self.syms:
                return []
            j = self.i + self.bs
            out = self.syms[self.i:j]
            if j >= len(self.syms):
                random.shuffle(self.syms)
                self.i = 0
            else:
                self.i = j
            return out

logger = logging.getLogger("algogpt.autoexec")

EXECUTOR_RUNNING = False
EXECUTOR_LAST_TS: Optional[float] = None
EXECUTOR_LOGS: deque[dict] = deque(maxlen=400)

INTERVAL = os.getenv("DEFAULT_INTERVAL", getattr(cfg, "DEFAULT_INTERVAL", "15m"))
SCAN_INTERVAL_BASE = int(os.getenv("SCAN_INTERVAL", str(getattr(cfg, "SCAN_INTERVAL", 60))))
MAX_TRADES_PER_TICK = int(os.getenv("MAX_TRADES_PER_TICK", "1"))
SYMBOL_COOLDOWN_SEC = int(os.getenv("SYMBOL_COOLDOWN_SEC", "600"))

QUALITY_THRESHOLD = float(os.getenv("MIN_QUALITY_SCORE", str(getattr(cfg, "MIN_QUALITY_SCORE", 8.5))))
SCAN_CONCURRENCY = int(os.getenv("SCAN_CONCURRENCY", "4"))
TIME_BUDGET_SEC = float(os.getenv("SCAN_TIME_BUDGET_SEC", "7.5"))

# Auto-tune (עדין)
AUTO_TUNE_ENABLE = os.getenv("AUTO_TUNE_ENABLE", "1").lower() in ("1","true","yes","on")
AUTO_TUNE_MIN = int(os.getenv("AUTO_TUNE_MIN_SCAN_INTERVAL", str(SCAN_INTERVAL_BASE)))
AUTO_TUNE_MAX = int(os.getenv("AUTO_TUNE_MAX_SCAN_INTERVAL", str(max(SCAN_INTERVAL_BASE, 180))))
AUTO_TUNE_UP_FACTOR = float(os.getenv("AUTO_TUNE_UP_FACTOR", "1.5"))
AUTO_TUNE_DOWN_FACTOR = float(os.getenv("AUTO_TUNE_DOWN_FACTOR", "0.85"))
AUTO_TUNE_STREAK_NO_TRADES = int(os.getenv("AUTO_TUNE_STREAK_NO_TRADES", "3"))

_last_trade_ts: Dict[str, float] = {}

def _log(event: str, level: str = "INFO", **kw):
    rec = {"event": event, **kw, "ts": time.time(), "level": level}
    EXECUTOR_LOGS.append(rec)
    getattr(logger, level.lower(), logger.info)(rec)

def _decide_side(row: Dict[str, Any]) -> Optional[str]:
    e21, e50 = row.get("ema_21"), row.get("ema_50")
    if e21 is None or e50 is None:
        return None
    if e21 > e50: return "LONG"
    if e21 < e50: return "SHORT"
    return None

def _quality_score(row: Dict[str, Any], side: str) -> float:
    score = 0.0
    if side == "LONG" and row.get("ema_21", 0) > row.get("ema_50", 0): score += 3.0
    if side == "SHORT" and row.get("ema_21", 0) < row.get("ema_50", 0): score += 3.0
    hist = float(row.get("macd_hist") or 0.0)
    if (side == "LONG" and hist > 0) or (side == "SHORT" and hist < 0): score += 2.0
    adx_v = float(row.get("adx") or 0.0)
    if adx_v >= 30: score += 3.0
    elif adx_v >= 25: score += 2.5
    elif adx_v >= 20: score += 1.5
    rsi_v = float(row.get("rsi") or 50.0)
    if 42 <= rsi_v <= 68: score += 1.0
    return max(0.0, min(10.0, score))

def _pick_leverage(adx_v: float) -> int:
    base = 7
    if adx_v >= 30: base = 15
    elif adx_v >= 25: base = 12
    elif adx_v >= 20: base = 9
    return int(max(getattr(cfg, "MIN_LEVERAGE", 5), min(base, getattr(cfg, "MAX_LEVERAGE", 35))))

def _derive_sl_tp(entry: float, atr_v: float, side: str, adx_v: float) -> tuple[float, float]:
    sl_mult = float(getattr(cfg, "STOP_LOSS_ATR_MULTIPLIER", 1.5))
    tp_mult = 3.5 if adx_v >= 25 else 2.5
    if side == "LONG":
        sl = entry - sl_mult * atr_v
        tp = entry + tp_mult * atr_v
    else:
        sl = entry + sl_mult * atr_v
        tp = entry - tp_mult * atr_v
    return float(sl), float(tp)

async def _scan_symbol(symbol: str) -> Optional[Dict[str, Any]]:
    try:
        last = _last_trade_ts.get(symbol, 0.0)
        if (time.time() - last) < SYMBOL_COOLDOWN_SEC:
            return None

        df: pd.DataFrame = get_klines_sync(symbol, interval=INTERVAL, limit=200)
        if df is None or df.empty:
            _log("no_klines", symbol=symbol, level="WARNING")
            return None

        ind = prepare_indicators_for_backtest(df)
        if ind.empty:
            _log("indicators_empty", symbol=symbol, level="WARNING")
            return None
        row = ind.iloc[-1].to_dict()

        side = _decide_side(row)
        if not side:
            return None

        # Anchor gate
        anchor = evaluate_anchor(side)
        if not getattr(anchor, "allow", True):
            _log("anchor_block", symbol=symbol, anchor=getattr(anchor, "__dict__", {}))
            return None

        # Quality gate
        q = _quality_score(row, side)
        if q < QUALITY_THRESHOLD:
            _log("quality_below_threshold", symbol=symbol, score=q, thr=QUALITY_THRESHOLD)
            return None

        entry = float(row.get("close") or df["close"].iloc[-1])
        atr_v = float(row.get("atr") or 0.0)
        adx_v = float(row.get("adx") or 0.0)
        if entry <= 0 or atr_v <= 0:
            _log("bad_entry_atr", symbol=symbol, entry=entry, atr=atr_v, level="WARNING")
            return None

        # ✅ Risk gate
        if RISK_CHECK_ENABLE:
            risk = pre_trade_risk_check(symbol, "BUY" if side=="LONG" else "SELL", _pick_leverage(adx_v), entry)
            if not risk.get("ok", True):
                _log("risk_reject", symbol=symbol, risk=risk)
                return None

        sl, tp = _derive_sl_tp(entry, atr_v, side, adx_v)
        lev = _pick_leverage(adx_v)
        return {"symbol": symbol, "side": side, "entry": entry, "sl": sl, "tp": tp,
                "leverage": lev, "score": q, "adx": adx_v, "atr": atr_v}
    except Exception as e:
        _log("scan_error", symbol=symbol, error=str(e), level="ERROR")
        return None

async def _execute_plan(plan: Dict[str, Any]) -> Dict[str, Any]:
    loop = asyncio.get_event_loop()
    resp = await loop.run_in_executor(
        None,
        lambda: execute_trade_live(
            symbol=plan["symbol"], side="BUY" if plan["side"] == "LONG" else "SELL",
            budget=float(getattr(cfg, "MAX_TRADE_BUDGET", 100.0)),
            leverage=int(plan["leverage"]),
            sl=float(plan["sl"]), tp=float(plan["tp"]),
            position_side="BOTH",
            reduce_only=False,
        ),
    )
    if resp.get("ok"):
        _last_trade_ts[plan["symbol"]] = time.time()
        exec_on_trade_sent(plan["symbol"])  # ✅ expose
    return resp

async def _scan_batch(symbols: List[str], max_trades: int) -> int:
    trades_sent = 0
    sem = asyncio.Semaphore(SCAN_CONCURRENCY)
    results: List[Dict[str, Any]] = []

    async def worker(sym: str):
        async with sem:
            plan = await _scan_symbol(sym)
            if plan: results.append(plan)

    tasks = [asyncio.create_task(worker(s)) for s in symbols]
    try:
        await asyncio.wait_for(asyncio.gather(*tasks), timeout=TIME_BUDGET_SEC)
    except asyncio.TimeoutError:
        _log("batch_timeout", count=len(symbols), level="WARNING")
        exec_on_batch_timeout()  # ✅ expose

    results.sort(key=lambda p: p.get("score", 0.0), reverse=True)
    for plan in results:
        if trades_sent >= max_trades: break
        resp = await _execute_plan(plan)
        _log("trade_attempt", symbol=plan["symbol"], plan={"side": plan["side"], "entry": plan["entry"]},
             resp_ok=bool(resp.get("ok")))
        if resp.get("ok"): trades_sent += 1
    return trades_sent

# ======================== Main Loop ========================
async def auto_scan_and_trade():
    global EXECUTOR_RUNNING, EXECUTOR_LAST_TS
    EXECUTOR_RUNNING = True
    try:
        wl = load_watchlist_env_or_fallback()  # ✅ דינמי + Fallback
        if "BTCUSDT" not in wl: wl.insert(0, "BTCUSDT")
        sched = SymbolScheduler(wl)

        # Auto-backoff state
        current_interval = SCAN_INTERVAL_BASE
        no_trade_streak = 0

        while EXECUTOR_RUNNING:
            tic = time.time()
            EXECUTOR_LAST_TS = tic
            if circuit_breaker_open():
                _log("circuit_open_skip_tick", level="WARNING")
                await asyncio.sleep(current_interval)
                continue

            batch = sched.next_batch()
            sent = 0
            try:
                sent = await _scan_batch(batch, MAX_TRADES_PER_TICK)
            except Exception as e:
                _log("scan_batch_error", error=str(e), level="ERROR")
                await notify_scan_error(str(e))

            if sent == 0:
                await notify_no_trades()
                no_trade_streak += 1
            else:
                no_trade_streak = 0

            # Auto-backoff (עדין וללא שבירה)
            if AUTO_TUNE_ENABLE:
                if no_trade_streak >= AUTO_TUNE_STREAK_NO_TRADES:
                    current_interval = int(min(AUTO_TUNE_MAX, max(current_interval * AUTO_TUNE_UP_FACTOR, current_interval + 5)))
                    _log("scan_interval_backoff", new_interval=current_interval)
                elif sent > 0 and current_interval > AUTO_TUNE_MIN:
                    current_interval = int(max(AUTO_TUNE_MIN, current_interval * AUTO_TUNE_DOWN_FACTOR))
                    _log("scan_interval_relax", new_interval=current_interval)

            dt = time.time() - tic
            # ✅ חשיפת קאונטרים + Ops tick (כולל Price-Drift אם נתמך)
            exec_on_tick_stop(dt_ms=float(dt*1000.0), current_interval=int(current_interval), no_trade_streak=int(no_trade_streak))
            ops_tick_safe()

            sleep_s = max(0.0, current_interval - dt)
            await asyncio.sleep(sleep_s)
    finally:
        EXECUTOR_RUNNING = False
        EXECUTOR_LAST_TS = None
        _log("executor_stopped")

def is_executor_running() -> bool:
    return EXECUTOR_RUNNING

def start_executor():
    global EXECUTOR_RUNNING
    if EXECUTOR_RUNNING:
        _log("executor_already_running")
        return
    _log("executor_starting")
    loop = asyncio.get_event_loop()
    if loop.is_running():
        loop.create_task(auto_scan_and_trade())
    else:
        loop.run_until_complete(auto_scan_and_trade())

def stop_executor():
    global EXECUTOR_RUNNING
    if EXECUTOR_RUNNING:
        EXECUTOR_RUNNING = False
        _log("executor_stopping")
    else:
        _log("executor_not_running")





























































































