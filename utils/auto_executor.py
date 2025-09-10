# utils/auto_executor.py
from __future__ import annotations
import asyncio, logging, os, time, random, math
from collections import deque
from typing import Optional, Dict, Any, List, Tuple

import pandas as pd

from utils import config as cfg
from utils.indicators import prepare_indicators_for_backtest
from utils.get_klines import get_klines_sync
from utils.anchor import evaluate_anchor
from utils.trade_executor import execute_trade_live  # ✅ סינכרוני
from utils.watchlist_utils import load_watchlist_env_or_fallback

# NEW: counters exposure
try:
    from utils.runtime_counters import (
        exec_on_tick_stop, exec_on_batch_timeout, exec_on_trade_sent, ops_tick_safe,
        ws_user_status, exec_get_counters
    )
except Exception:
    def exec_on_tick_stop(*a, **k): pass
    def exec_on_batch_timeout(*a, **k): pass
    def exec_on_trade_sent(*a, **k): pass
    def ops_tick_safe(): pass
    def ws_user_status() -> Dict[str, Any]: return {"running": False, "ttl_sec": None, "reconnects": None, "inter_event_ewma_ms": None}
    def exec_get_counters() -> Dict[str, Any]: return {"tick_p95_ms": None, "timeouts_burst": 0}

# NEW: leverage policy
try:
    from utils.leverage_policy import adjust_leverage  # adjust_leverage(adx, proposed, symbol=None)
except Exception:
    def adjust_leverage(adx: float, proposed_leverage: int, symbol: Optional[str] = None) -> int:  # type: ignore
        return int(proposed_leverage)

# NEW: optional risk gate (pre-trade)
RISK_CHECK_ENABLE = os.getenv("RISK_CHECK_ENABLE", "0").lower() in ("1","true","yes","on")
if RISK_CHECK_ENABLE:
    try:
        from utils.risk import pre_trade_risk_check  # pre_trade_risk_check(symbol, side, leverage, ref_price) -> {"ok": bool, ...}
    except Exception:
        RISK_CHECK_ENABLE = False

# Notifications (כולל Explain)
try:
    from utils.telegram_notifier import notify_no_trades, notify_scan_error, notify_explain_trade
except Exception:
    async def notify_no_trades(): return None
    async def notify_scan_error(reason: str): return None
    async def notify_explain_trade(plan: Dict[str, Any]): return None

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

# Optional: Binance preflight helpers
try:
    from utils.binance_client import fapi_ping, futures_exchange_info_safe, get_price
except Exception:
    def fapi_ping() -> bool: return False
    def futures_exchange_info_safe(*a, **k): return None
    def get_price(symbol: str): return None

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

# ===== Preflight / Health-SLA =====
PRE_FLIGHT_ENABLE = os.getenv("PRE_FLIGHT_ENABLE", "1").lower() in ("1","true","yes","on")
PREFLIGHT_MAX_SKEW_MS = int(os.getenv("PREFLIGHT_MAX_SKEW_MS", "2500"))
HEALTH_SLA_ENABLE = os.getenv("HEALTH_SLA_ENABLE", "1").lower() in ("1","true","yes","on")
HEALTH_TTL_MAX_SEC = int(os.getenv("HEALTH_TTL_MAX_SEC", "15"))
HEALTH_MAX_TIMEOUT_BURST = int(os.getenv("HEALTH_MAX_TIMEOUT_BURST", "5"))
HEALTH_MAX_TICK_P95_MS = int(os.getenv("HEALTH_MAX_TICK_P95_MS", "2200"))
HEALTH_PAUSE_SEC = int(os.getenv("HEALTH_PAUSE_SEC", "20"))

# ===== Canary Mode =====
CANARY_ENABLE = os.getenv("CANARY_ENABLE", "1").lower() in ("1","true","yes","on")
CANARY_MODE = os.getenv("CANARY_MODE", "DRY").upper()  # DRY | LIVE
CANARY_MAX_TRADES = int(os.getenv("CANARY_MAX_TRADES", "1"))
CANARY_WINDOW_SEC = int(os.getenv("CANARY_WINDOW_SEC", "1800"))
_canary_window_start: float = 0.0
_canary_trades: int = 0

# ===== Auto-tune (בסיס) =====
AUTO_TUNE_ENABLE = os.getenv("AUTO_TUNE_ENABLE", "1").lower() in ("1","true","yes","on")
AUTO_TUNE_MIN = int(os.getenv("AUTO_TUNE_MIN_SCAN_INTERVAL", str(SCAN_INTERVAL_BASE)))
AUTO_TUNE_MAX = int(os.getenv("AUTO_TUNE_MAX_SCAN_INTERVAL", str(max(SCAN_INTERVAL_BASE, 180))))
AUTO_TUNE_UP_FACTOR = float(os.getenv("AUTO_TUNE_UP_FACTOR", "1.5"))
AUTO_TUNE_DOWN_FACTOR = float(os.getenv("AUTO_TUNE_DOWN_FACTOR", "0.85"))
AUTO_TUNE_STREAK_NO_TRADES = int(os.getenv("AUTO_TUNE_STREAK_NO_TRADES", "3"))

# ===== Burst הזדמנויות (Cap hit) – קיצור מרווח =====
AUTO_TUNE_BURST_DOWN_FACTOR = float(os.getenv("AUTO_TUNE_BURST_DOWN_FACTOR", "0.6"))

# ===== Burst של TIMEOUTS – backoff + הורדת concurrency =====
TIMEOUTS_BURST_AGGR_THRESHOLD = int(os.getenv("TIMEOUTS_BURST_AGGR_THRESHOLD", "3"))
BURST_BACKOFF_FACTOR = float(os.getenv("BURST_BACKOFF_FACTOR", "1.35"))
BURST_CONC_FRACTION = float(os.getenv("BURST_CONC_FRACTION", "0.7"))
BURST_MIN_CONC = int(os.getenv("BURST_MIN_CONC", "2"))
BURST_COOLDOWN_SEC = int(os.getenv("BURST_COOLDOWN_SEC", "120"))

# ===== Opportunity Boost – העלאת concurrency כשיש הרבה מועמדים =====
OPP_BOOST_ENABLE = os.getenv("OPP_BOOST_ENABLE", "1").lower() in ("1","true","yes","on")
OPP_BATCH_VIABLE_THRESHOLD = int(os.getenv("OPP_BATCH_VIABLE_THRESHOLD", "3"))
OPP_CONC_BOOST_FACTOR = float(os.getenv("OPP_CONC_BOOST_FACTOR", "1.5"))
OPP_MAX_CONC = int(os.getenv("OPP_MAX_CONC", str(max(SCAN_CONCURRENCY, 8))))
OPP_COOLDOWN_SEC = int(os.getenv("OPP_COOLDOWN_SEC", "90"))
OPP_DECAY_FACTOR = float(os.getenv("OPP_DECAY_FACTOR", "0.8"))

_last_trade_ts: Dict[str, float] = {}

# Burst/Timeout state
_timeout_burst_count: int = 0
_burst_mode_until: float = 0.0
_effective_concurrency: int = SCAN_CONCURRENCY
# Opportunity-boost state
_opp_boost_until: float = 0.0

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

# -------------------- Preflight & Health --------------------
def _time_skew_ok() -> bool:
    try:
        from utils.binance_client import get_futures_client
        cli = get_futures_client()
        offset = getattr(cli, "TIME_OFFSET", 0)
        return abs(int(offset)) <= PREFLIGHT_MAX_SKEW_MS
    except Exception:
        return True  # לא חוסם אם אין גישה למדידה

def _ws_ok() -> bool:
    try:
        status = ws_user_status()
        ttl = status.get("ttl_sec")
        running = bool(status.get("running"))
        if ttl is None:
            return running
        return running and (float(ttl) <= HEALTH_TTL_MAX_SEC)
    except Exception:
        return True

def _exchange_info_ok() -> bool:
    try:
        info = futures_exchange_info_safe()
        return bool(info and info.get("symbols"))
    except Exception:
        return False

async def _warmup():
    try:
        # מחמם מחירים/אינדיקטורים ל־BTC
        _ = get_price("BTCUSDT")
        _ = get_klines_sync("BTCUSDT", interval=INTERVAL, limit=100)
    except Exception:
        pass

async def _preflight_gate() -> bool:
    if not PRE_FLIGHT_ENABLE:
        return True
    ok = True
    if not fapi_ping():
        _log("preflight_ping_fail", level="ERROR"); ok = False
    if not _time_skew_ok():
        _log("preflight_time_skew", max_skew_ms=PREFLIGHT_MAX_SKEW_MS, level="ERROR"); ok = False
    if not _exchange_info_ok():
        _log("preflight_exchange_info_fail", level="ERROR"); ok = False
    if not _ws_ok():
        _log("preflight_ws_ttl_fail", ttl_max=HEALTH_TTL_MAX_SEC, level="ERROR"); ok = False
    if ok:
        await _warmup()
        _log("preflight_ok")
    return ok

def _health_ok() -> bool:
    if not HEALTH_SLA_ENABLE:
        return True
    try:
        ws_ok = _ws_ok()
        ex = exec_get_counters()
        p95 = ex.get("tick_p95_ms") or 0
        burst = int(ex.get("timeouts_burst") or 0)
        return ws_ok and (p95 <= HEALTH_MAX_TICK_P95_MS or p95 == 0) and (burst < HEALTH_MAX_TIMEOUT_BURST)
    except Exception:
        return True

# -------------------- Scan / Build Plan --------------------
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
        lev_raw = _pick_leverage(adx_v)
        lev = adjust_leverage(adx_v, lev_raw, symbol=symbol)  # ✅ עם cap פר-סימבול/דריפט

        plan: Dict[str, Any] = {
            "symbol": symbol, "side": side, "entry": entry, "sl": sl, "tp": tp,
            "leverage": lev, "score": q, "adx": adx_v, "atr": atr_v,
            "ema_21": row.get("ema_21"), "ema_50": row.get("ema_50"),
            "macd_hist": row.get("macd_hist"), "rsi": row.get("rsi"),
        }
        return plan
    except Exception as e:
        _log("scan_error", symbol=symbol, error=str(e), level="ERROR")
        return None

# -------------------- Execution (w/ Canary) --------------------
def _canary_allow() -> Tuple[bool, str]:
    if not CANARY_ENABLE:
        return (True, "disabled")
    now = time.time()
    global _canary_window_start, _canary_trades
    if _canary_window_start == 0.0 or (now - _canary_window_start) > CANARY_WINDOW_SEC:
        _canary_window_start = now
        _canary_trades = 0
    if CANARY_MODE == "DRY":
        return (False, "dry")
    # LIVE: טרייד אחד בלבד בחלון
    if _canary_trades >= CANARY_MAX_TRADES:
        return (False, "limit")
    return (True, "live")

async def _execute_plan(plan: Dict[str, Any]) -> Dict[str, Any]:
    allowed, reason = _canary_allow()
    if not allowed:
        if reason == "dry":
            # DRY-Run → הסבר בלבד
            try:
                await notify_explain_trade(plan)
            except Exception:
                pass
            _log("canary_dry_skip", symbol=plan["symbol"], reason="canary_dry")
            return {"ok": True, "dry": True, "reason": "canary_dry"}
        _log("canary_live_block", symbol=plan["symbol"], reason="limit")
        return {"ok": False, "error": "canary_limit"}

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
        exec_on_trade_sent(plan["symbol"])
        try:
            await notify_explain_trade(plan)  # ✅ Explain (עם קירור/Rate Limit פנימי)
        except Exception:
            pass
        if CANARY_ENABLE and CANARY_MODE == "LIVE":
            # ספירת טריידים בחלון
            global _canary_trades
            _canary_trades += 1
    return resp

# -------------------- Batch --------------------
async def _scan_batch(symbols: List[str], max_trades: int, concurrency: int) -> Tuple[int, bool, int]:
    trades_sent = 0
    sem = asyncio.Semaphore(max(1, int(concurrency)))
    results: List[Dict[str, Any]] = []
    timed_out = False

    async def worker(sym: str):
        async with sem:
            plan = await _scan_symbol(sym)
            if plan: results.append(plan)

    tasks = [asyncio.create_task(worker(s)) for s in symbols]
    try:
        await asyncio.wait_for(asyncio.gather(*tasks), timeout=TIME_BUDGET_SEC)
    except asyncio.TimeoutError:
        timed_out = True
        _log("batch_timeout", count=len(symbols), conc=int(concurrency), level="WARNING")
        exec_on_batch_timeout()

    viable_count = len(results)

    results.sort(key=lambda p: p.get("score", 0.0), reverse=True)
    for plan in results:
        if trades_sent >= max_trades: break
        resp = await _execute_plan(plan)
        _log("trade_attempt", symbol=plan["symbol"], plan={"side": plan["side"], "entry": plan["entry"]},
             resp_ok=bool(resp.get("ok")))
        if resp.get("ok"): trades_sent += 1
    return trades_sent, timed_out, viable_count

# -------------------- Main Loop --------------------
async def auto_scan_and_trade():
    global EXECUTOR_RUNNING, EXECUTOR_LAST_TS
    global _timeout_burst_count, _burst_mode_until, _effective_concurrency, _opp_boost_until

    EXECUTOR_RUNNING = True
    try:
        if PRE_FLIGHT_ENABLE:
            ok = await _preflight_gate()
            if not ok:
                _log("preflight_block_start", level="ERROR")
                return

        wl = load_watchlist_env_or_fallback()
        if "BTCUSDT" not in wl: wl.insert(0, "BTCUSDT")
        sched = SymbolScheduler(wl)

        current_interval = SCAN_INTERVAL_BASE
        no_trade_streak = 0
        _effective_concurrency = SCAN_CONCURRENCY
        _opp_boost_until = 0.0
        last_burst_trades_ts = 0.0

        while EXECUTOR_RUNNING:
            tic = time.time()
            EXECUTOR_LAST_TS = tic
            if circuit_breaker_open():
                _log("circuit_open_skip_tick", level="WARNING")
                await asyncio.sleep(current_interval)
                continue

            # Health-Gate (PAUSE)
            if not _health_ok():
                _log("health_pause", ttl_max=HEALTH_TTL_MAX_SEC, p95_max=HEALTH_MAX_TICK_P95_MS,
                     timeout_burst_max=HEALTH_MAX_TIMEOUT_BURST, level="WARNING")
                await asyncio.sleep(HEALTH_PAUSE_SEC)
                continue

            now = time.time()

            if _burst_mode_until and now >= _burst_mode_until:
                prev = _effective_concurrency
                _effective_concurrency = SCAN_CONCURRENCY
                _burst_mode_until = 0.0
                _timeout_burst_count = 0
                _log("timeout_burst_cleared", conc_prev=prev, conc_new=_effective_concurrency)

            if _opp_boost_until and now >= _opp_boost_until and _burst_mode_until == 0.0:
                prev = _effective_concurrency
                new_conc = max(SCAN_CONCURRENCY, int(math.floor(_effective_concurrency * OPP_DECAY_FACTOR)))
                if new_conc <= SCAN_CONCURRENCY:
                    _effective_concurrency = SCAN_CONCURRENCY
                    _opp_boost_until = 0.0
                    _log("opp_boost_cleared", conc_prev=prev, conc_new=_effective_concurrency)
                else:
                    _effective_concurrency = new_conc
                    _opp_boost_until = now + OPP_COOLDOWN_SEC
                    _log("opp_boost_decay_step", conc_prev=prev, conc_new=_effective_concurrency, next_decay_sec=OPP_COOLDOWN_SEC)

            batch = sched.next_batch()
            conc_this_tick = min(_effective_concurrency, max(1, len(batch)))

            try:
                sent, timed_out, viable_count = await _scan_batch(batch, MAX_TRADES_PER_TICK, conc_this_tick)
            except Exception as e:
                _log("scan_batch_error", error=str(e), level="ERROR")
                await notify_scan_error(str(e))
                sent, timed_out, viable_count = 0, False, 0

            if sent == 0:
                await notify_no_trades()
                no_trade_streak += 1
            else:
                no_trade_streak = 0

            if (
                AUTO_TUNE_ENABLE and OPP_BOOST_ENABLE and _burst_mode_until == 0.0
                and not timed_out and viable_count >= OPP_BATCH_VIABLE_THRESHOLD
            ):
                prev = _effective_concurrency
                boosted = int(max(prev, math.ceil(SCAN_CONCURRENCY * OPP_CONC_BOOST_FACTOR)))
                boosted = min(boosted, OPP_MAX_CONC)
                boosted = min(boosted, max(1, len(batch)))
                if boosted > prev:
                    _effective_concurrency = boosted
                    _opp_boost_until = now + OPP_COOLDOWN_SEC
                    _log("opp_boost_enter",
                         conc_prev=prev, conc_new=_effective_concurrency,
                         viable=viable_count, threshold=OPP_BATCH_VIABLE_THRESHOLD,
                         cooldown_sec=OPP_COOLDOWN_SEC)

            if AUTO_TUNE_ENABLE and sent >= MAX_TRADES_PER_TICK and (now - last_burst_trades_ts) >= 45:
                prev_interval = current_interval
                current_interval = int(max(AUTO_TUNE_MIN, current_interval * AUTO_TUNE_BURST_DOWN_FACTOR))
                last_burst_trades_ts = now
                _log("burst_trades_cap_hit",
                     prev_interval=prev_interval, new_interval=current_interval,
                     sent=sent, cap=MAX_TRADES_PER_TICK)

            if AUTO_TUNE_ENABLE:
                if timed_out:
                    _timeout_burst_count += 1
                else:
                    _timeout_burst_count = 0

                if _timeout_burst_count >= TIMEOUTS_BURST_AGGR_THRESHOLD and _burst_mode_until == 0.0:
                    prev_interval = current_interval
                    prev_conc = _effective_concurrency
                    current_interval = int(min(AUTO_TUNE_MAX, max(AUTO_TUNE_MIN, int(current_interval * BURST_BACKOFF_FACTOR))))
                    _effective_concurrency = max(BURST_MIN_CONC, int(max(1, round(SCAN_CONCURRENCY * BURST_CONC_FRACTION))))
                    _burst_mode_until = now + BURST_COOLDOWN_SEC
                    _opp_boost_until = 0.0
                    _log("timeout_burst_enter",
                         prev_interval=prev_interval, new_interval=current_interval,
                         conc_prev=prev_conc, conc_new=_effective_concurrency,
                         cooldown_sec=BURST_COOLDOWN_SEC,
                         timeouts_in_row=_timeout_burst_count)
                elif _burst_mode_until == 0.0:
                    if no_trade_streak >= AUTO_TUNE_STREAK_NO_TRADES:
                        prev_interval = current_interval
                        current_interval = int(min(AUTO_TUNE_MAX, max(current_interval * AUTO_TUNE_UP_FACTOR, current_interval + 5)))
                        _log("scan_interval_backoff",
                             prev_interval=prev_interval, new_interval=current_interval,
                             reason="no_trades_streak", streak=no_trade_streak)
                    elif sent > 0 and current_interval > AUTO_TUNE_MIN:
                        prev_interval = current_interval
                        current_interval = int(max(AUTO_TUNE_MIN, current_interval * AUTO_TUNE_DOWN_FACTOR))
                        _log("scan_interval_relax", prev_interval=prev_interval, new_interval=current_interval)

            dt = time.time() - tic
            exec_on_tick_stop(dt_ms=float(dt * 1000.0), current_interval=int(current_interval), no_trade_streak=int(no_trade_streak))
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




































































































