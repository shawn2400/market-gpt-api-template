# utils/metrics_exporter.py
from prometheus_client import Counter, Gauge, Histogram

# Trades
trades_open_total = Gauge("algogpt_trades_open_total","מספר פוזיציות פתוחות כרגע")
trades_closed_total = Counter("algogpt_trades_closed_total","סה\"כ פוזיציות שנסגרו")
pnl_total = Gauge("algogpt_pnl_total_usdt","PnL מצטבר (USDT)")

# TP / SL
tp_hits_total = Counter("algogpt_tp_hits_total","כמה פעמים TP הופעל",["level"])
sl_hits_total = Counter("algogpt_sl_hits_total","כמה פעמים SL הופעל")
breakeven_moves_total = Counter("algogpt_breakeven_moves_total","SL הוזז ל-BE")
trailing_moves_total = Counter("algogpt_trailing_moves_total","SL הוזז ע\"י Trailing")

# Approvals
approvals_total = Counter("algogpt_approvals_total","מספר אישורים/דחיות",["status"])

# AI
ai_requests_total = Counter("algogpt_ai_requests_total","סה\"כ בקשות ל-AI",["status"])
ai_latency_seconds = Histogram("algogpt_ai_latency_seconds","לטנסי קריאות AI",buckets=(0.2,0.5,1,2,3,5,10))

# API
api_requests_total = Counter("algogpt_api_requests_total","סה\"כ בקשות API",["path","method","status"])
api_latency_seconds = Histogram("algogpt_api_latency_seconds","לטנסי API לפי נתיב",["path"],buckets=(0.01,0.05,0.1,0.25,0.5,1,2,5))
api_5xx_total = Counter("algogpt_api_5xx_total","סה\"כ שגיאות API 5xx")

# Executor/Grid
auto_executor_enabled = Gauge("algogpt_auto_executor_enabled","Auto Executor (1=on,0=off)")
grid_enabled = Gauge("algogpt_grid_enabled","Grid מצב (1=on,0=off)")

# Telegram
telegram_sent_total = Counter("algogpt_telegram_messages_sent_total","מספר הודעות שנשלחו")
telegram_failed_total = Counter("algogpt_telegram_messages_failed_total","מספר הודעות שנכשלו")

# Helpers
def record_trade_open(c): trades_open_total.set(c)
def record_trade_close(): trades_closed_total.inc()
def record_pnl(v): pnl_total.set(v)
def record_tp_hit(level): tp_hits_total.labels(level=level).inc()
def record_sl_hit(): sl_hits_total.inc()
def record_breakeven(): breakeven_moves_total.inc()
def record_trailing(): trailing_moves_total.inc()
def record_approval(status): approvals_total.labels(status=status).inc()
def record_ai_call(status,lat): ai_requests_total.labels(status=status).inc(); ai_latency_seconds.observe(lat)
def record_api_request(path,method,status,lat):
    api_requests_total.labels(path=path,method=method,status=status).inc()
    api_latency_seconds.labels(path=path).observe(lat)
    if int(status) >= 500: api_5xx_total.inc()
def set_auto_executor(on): auto_executor_enabled.set(1 if on else 0)
def set_grid(on): grid_enabled.set(1 if on else 0)
def record_telegram_sent(): telegram_sent_total.inc()
def record_telegram_failed(): telegram_failed_total.inc()




