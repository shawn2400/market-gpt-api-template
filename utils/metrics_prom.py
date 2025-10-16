# utils/metrics_prom.py
from __future__ import annotations
import os
from typing import Optional
from prometheus_client import Counter, Histogram, Gauge

# Counters
fills_seen_total = Counter("fills_seen_total", "Total fills observed", ["symbol", "leg"])
profit_lock_actions_total = Counter("profit_lock_actions_total", "Profit-lock / BE actions", ["symbol", "action"])

# Histograms (גבולות ריאליים, ניתנים לשינוי דרך ENV)
def _buckets_from_env(name: str, default: str):
    raw = os.getenv(name, default)
    try:
        return [float(x) for x in raw.split(",")]
    except Exception:
        return [5, 15, 30, 60, 120, 300, 600, 1200]

time_to_tp1_seconds = Histogram(
    "time_to_tp1_seconds",
    "Time from entry to TP1 fill",
    buckets=_buckets_from_env("PROM_TTP1_BUCKETS", "15,30,60,120,300,600,1200,2400"),
)

# Gauges
rr_gauge = Gauge("trade_rr_now", "Current instantaneous RR", ["symbol"])

def inc_fill(symbol: str, leg: str):
    fills_seen_total.labels(symbol=symbol.upper(), leg=leg).inc()

def observe_ttp1(seconds: float):
    time_to_tp1_seconds.observe(float(seconds))

def set_rr(symbol: str, rr: float):
    rr_gauge.labels(symbol=symbol.upper()).set(float(rr))

def inc_profit_lock(symbol: str, action: str):
    profit_lock_actions_total.labels(symbol=symbol.upper(), action=action).inc()
