# -*- coding: utf-8 -*-
"""
Dynamic Trading Metrics for Prometheus
Counters and gauges for monitoring dynamic regime-based trading.
"""
from prometheus_client import Counter, Gauge
import logging

log = logging.getLogger(__name__)

# Decision tracking
dyn_decisions = Counter(
    "algogpt_dyn_decisions",
    "Dynamic trading decisions taken",
    ["symbol", "regime"]
)

dyn_skips = Counter(
    "algogpt_dyn_skips",
    "Dynamic decisions skipped",
    ["reason"]
)

dyn_errors = Counter(
    "algogpt_dyn_errors",
    "Dynamic path errors",
    ["stage"]
)

# Order updates
sl_changes = Counter(
    "algogpt_sl_changes",
    "Stop-loss updates via Zero-Gap manager",
    ["symbol"]
)

tp_sets = Counter(
    "algogpt_tp_sets",
    "TP ladder placements",
    ["symbol"]
)

# Safety guards
age_guard_hit = Counter(
    "algogpt_stale_guard_hits",
    "Stale data protection triggers"
)

conf_low_hit = Counter(
    "algogpt_low_conf_hits",
    "Low confidence guard triggers"
)

cb_blocks = Counter(
    "algogpt_circuit_blocks",
    "Circuit breaker blocks"
)

# State gauges
live_enforce = Gauge(
    "algogpt_dyn_enforce",
    "1 if enforce mode active, 0 if shadow"
)

regime_confidence = Gauge(
    "algogpt_regime_confidence",
    "Current regime detection confidence",
    ["symbol", "regime"]
)

log.info("[MetricsDyn] Prometheus metrics initialized for dynamic trading")
