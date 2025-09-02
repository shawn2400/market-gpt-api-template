# utils/auto_executor.py
from __future__ import annotations
import asyncio
import logging
import os
import time
from collections import deque
from typing import Optional, Dict, Any

import pandas as pd

from utils import config as cfg
from utils.indicators import prepare_indicators_for_backtest
from utils.binance_client import get_klines_df
from utils.anchor import evaluate_anchor
from utils.trade_executor import execute_trade_live
from utils.symbol_scheduler import pick_symbols, mark_scanned

logger = logging.getLogger("algogpt.autoexec")

EXECUTOR_RUNNING = False
EXECUTOR_LAST_TS: Optional[float] = None
EXECUTOR_LOGS: deque[dict] = deque(maxlen=300)

INTERVAL = os.getenv("DEFAULT_INTERVAL", getattr(cfg, "DEFAULT_INTERVAL", "15m"))
SCAN_INTERVAL = getattr(cfg, "SCAN_INTERVAL", 60)
MAX_TRADES_PER_TICK = int(os.getenv("MAX_TRADES_PER_TICK", "1"))
SYMBOL_COOLDOWN_SEC = int(os.getenv("SYMBOL_COOLDOWN_SEC", "600"))

SCAN_CONCURRENCY = int(os.getenv("SCAN_CONCURRENCY", "8"))
BATCH_PER_TICK = int(os.getenv("SCAN_MAX_LIMIT", "10"))

QUALITY_THRESHOLD = max(0.0, float(os.getenv("MIN_QUALITY_SCORE", str(getattr(cfg, "MIN_QUALITY_SCORE", 8.5)))))

_last_trade_ts: Dict[str, float] = {}

def _log(event: str, level: str = "INFO", **kw):
    rec = {"event": event, **kw, "ts": time.time(), "level": level}
    EXECUTOR_LOGS.append(rec)
    getattr(logger, level.lower(), logger.info)(rec)

def _decide_side(row: Dict[str, Any]) -> Optional[str]:
    e21, e50 = row.get("ema_21"), row.get("ema_50")
    if e21 is None or e50 is None:
        return None
    if e21 > e50:
        return "LONG"
    if e21 < e50:
        return "SHORT"
    return None

def _quality_score(row: Dict[str, Any], side: str) -> float:
    score = 0.0
    if side == "LONG" and row.get("ema_21", 0) > row.get("ema_50", 0):
        score += 3.0
    if side == "SHORT" and row.get("ema_21", 0) < row.get("ema_50", 0):
        score += 3.0
    hist = float(row.get("macd_hist") or 0.0)
    if (side == "LONG" and hist > 0) or (side == "SHORT" and hist < 0):
        score += 2.0
    adx_v = float(row.get("adx") or 0.0)
    if adx_v >= 25:
        score += 2.5
    elif adx_v >= 20:
        score += 1.5
    rsi_v = float(row.get("rsi") or 50.0)
    if 42 <= rsi_v <= 68:
        score += 1.0
    return max(0.0, min(10.0, score))

def _pick_leverage(adx_v: float) -> int:
    base = 7
    if adx_v >= 30:
        base = 15
    elif adx_v >= 25:
        base = 12
    elif adx_v >= 20:
        base = 9
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
            _log("cooldown_skip", symbol=symbol)
            return None

        df: pd.DataFrame = get_klines_df(symbol, interval=INTERVAL, limit=200)
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
            _log("no_side", symbol=symbol)
            return None

        anchor = evaluate_anchor(side)
        if not getattr(anchor, "allow", True):
            _log("anchor_block", symbol=symbol, anchor=anchor.__dict__)
            return None

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

        sl, tp = _derive_sl_tp(entry, atr_v, side, adx_v)
        lev = _pick_leverage(adx_v)

        return {
            "symbol": symbol,
            "side": side,
            "entry": entry,
            "sl": sl,
            "tp": tp,
            "leverage": lev,
            "score": q,
            "adx": adx_v,
            "atr": atr_v,
        }
    except Exception as e:
        _log("scan_error", symbol=symbol, error=str(e), level="ERROR")
        return None

async def _execute_plan(plan: Dict[str, Any]) -> Dict[str, Any]:
    dry = not getattr(cfg, "EXECUTE_TRADES", False)
    resp = await execute_trade_live(
        symbol=plan["symbol"],
        side=plan["side"],
        budget=float(getattr(cfg, "MAX_TRADE_BUDGET", 100.0)),
        leverage=int(plan["leverage"]),
        entry=float(plan["entry"]),
        sl=float(plan["sl"]),
        tp=float(plan["tp"]),
        dry_run=dry,
    )
    if resp.get("ok"):
        _last_trade_ts[plan["symbol"]] = time.time()
    return resp

async def auto_scan_and_trade():
    global EXECUTOR_RUNNING, EXECUTOR_LAST_TS
    EXECUTOR_RUNNING = True
    sem = asyncio.Semaphore(SCAN_CONCURRENCY)
    try:
        while EXECUTOR_RUNNING:
            EXECUTOR_LAST_TS = time.time()
            batch = await pick_symbols(BATCH_PER_TICK, cooldown_sec=SYMBOL_COOLDOWN_SEC)
            if "BTCUSDT" not in batch:
                batch.insert(0, "BTCUSDT")

            sent = 0
            async def _job(sym: str):
                nonlocal sent
                async with sem:
                    if sent >= MAX_TRADES_PER_TICK:
                        return
                    plan = await _scan_symbol(sym)
                    if not plan:
                        return
                    resp = await _execute_plan(plan)
                    _log("trade_attempt", symbol=sym, plan={"side":plan["side"],"entry":plan["entry"],"sl":plan["sl"],"tp":plan["tp"],"lev":plan["leverage"],"score":plan["score"]}, resp_ok=bool(resp.get("ok")))
                    if resp.get("ok"):
                        sent += 1

            tasks = [asyncio.create_task(_job(sym)) for sym in batch]
            await asyncio.gather(*tasks, return_exceptions=True)
            mark_scanned(batch)
            await asyncio.sleep(SCAN_INTERVAL)
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





















































































