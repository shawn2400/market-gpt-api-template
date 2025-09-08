from prometheus_client import Counter, Gauge, Histogram

# ───────────────────────────────
# Trades
# ───────────────────────────────
trades_open_total = Gauge("algogpt_trades_open_total", "מספר פוזיציות פתוחות כרגע")
trades_closed_total = Counter("algogpt_trades_closed_total", "סה\"כ פוזיציות שנסגרו")
pnl_total = Gauge("algogpt_pnl_total_usdt", "PnL מצטבר בכל הטריידים (USDT)")

# ───────────────────────────────
# TP / SL Ladder
# ───────────────────────────────
tp_hits_total = Counter("algogpt_tp_hits_total", "כמה פעמים TP הופעל לפי רמות", ["level"])
sl_hits_total = Counter("algogpt_sl_hits_total", "כמה פעמים SL הופעל")
breakeven_moves_total = Counter("algogpt_breakeven_moves_total", "כמה פעמים SL הוזז ל-BE")
trailing_moves_total = Counter("algogpt_trailing_moves_total", "כמה פעמים SL הוזז ע\"י Trailing")

# ───────────────────────────────
# Approvals
# ───────────────────────────────
approvals_total = Counter("algogpt_approvals_total", "מספר אישורים/דחיות", ["status"])

# ───────────────────────────────
# AI Analysis
# ───────────────────────────────
ai_requests_total = Counter("algogpt_ai_requests_total", "סה\"כ בקשות ל-AI", ["status"])
ai_latency_seconds = Histogram("algogpt_ai_latency_seconds", "לטנסי קריאות AI", buckets=(0.2, 0.5, 1, 2, 3, 5, 10))

# ───────────────────────────────
# API
# ───────────────────────────────
api_requests_total = Counter("algogpt_api_requests_total", "סה\"כ בקשות API", ["path", "method", "status"])
api_latency_seconds = Histogram("algogpt_api_latency_seconds", "לטנסי API לפי נתיב", ["path"], buckets=(0.01,0.05,0.1,0.25,0.5,1,2,5))
api_5xx_errors_total = Counter("algogpt_api_5xx_errors_total", "סה\"כ שגיאות 5xx ב-API")

# ───────────────────────────────
# Auto Executor
# ───────────────────────────────
auto_executor_enabled = Gauge("algogpt_auto_executor_enabled", "מצב Auto Executor (1=on, 0=off)")
grid_enabled = Gauge("algogpt_grid_enabled", "מצב Grid (1=on, 0=off)")

# ───────────────────────────────
# Telegram
# ───────────────────────────────
telegram_messages_sent_total = Counter("algogpt_telegram_messages_sent_total", "סה\"כ הודעות טלגרם שנשלחו")
telegram_messages_failed_total = Counter("algogpt_telegram_messages_failed_total", "סה\"כ הודעות טלגרם שנכשלו")

# ───────────────────────────────
# Helpers
# ───────────────────────────────
def record_trade_open(count): trades_open_total.set(count)
def record_trade_close(): trades_closed_total.inc()
def record_pnl(v): pnl_total.set(v)
def record_tp_hit(level): tp_hits_total.labels(level=level).inc()
def record_sl_hit(): sl_hits_total.inc()
def record_breakeven(): breakeven_moves_total.inc()
def record_trailing(): trailing_moves_total.inc()
def record_approval(status): approvals_total.labels(status=status).inc()
def record_ai_call(status, latency): ai_requests_total.labels(status=status).inc(); ai_latency_seconds.observe(latency)
def record_api_request(path, method, status, latency):
    api_requests_total.labels(path=path, method=method, status=status).inc()
    api_latency_seconds.labels(path=path).observe(latency)
    if str(status).startswith("5"):
        api_5xx_errors_total.inc()
def set_auto_executor(on): auto_executor_enabled.set(1 if on else 0)
def set_grid(on): grid_enabled.set(1 if on else 0)
def record_telegram_sent(): telegram_messages_sent_total.inc()
def record_telegram_failed(): telegram_messages_failed_total.inc()



