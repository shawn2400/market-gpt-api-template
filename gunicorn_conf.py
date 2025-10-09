# gunicorn_conf.py
import os

# Bind
bind = f"0.0.0.0:{int(os.getenv('PORT', '10000') or '10000')}"

# Workers/threads – לוקח מ-WEB_CONCURRENCY אם יש, אחרת WORKERS, אחרת 1
workers = int(
    os.getenv("WEB_CONCURRENCY")
    or os.getenv("WORKERS", "1")
)
threads = int(os.getenv("GTHREADS", "1") or "1")

# Worker class
worker_class = "uvicorn.workers.UvicornWorker"

# Timeouts / keepalive
timeout = int(os.getenv("GUNICORN_TIMEOUT", os.getenv("TIMEOUT", "120")) or "120")
graceful_timeout = int(os.getenv("GUNICORN_GRACEFUL_TIMEOUT", os.getenv("GRACEFUL_TIMEOUT", "30")) or "30")
keepalive = int(os.getenv("GUNICORN_KEEPALIVE", os.getenv("KEEPALIVE", "5")) or "5")

# Logs
accesslog = "-"
errorlog = "-"
loglevel = os.getenv("LOG_LEVEL", "info").lower()
access_log_format = '%(h)s %(l)s %(u)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s"'

# Resilience (גלגול וורקרים כדי להימנע מדליפות זיכרון)
max_requests = int(os.getenv("MAX_REQUESTS", "1000") or "1000")
max_requests_jitter = int(os.getenv("MAX_REQUESTS_JITTER", "50") or "50")

# Proxy / Forwarded headers (Render / פרוקסי)
forwarded_allow_ips = os.getenv("FORWARDED_ALLOW_IPS", "*")
proxy_allow_ips = "*"

# Pass env down to workers (uvicorn)
raw_env = []
for key in ("UVICORN_LOG_LEVEL", "UVICORN_ACCESS_LOG", "PYTHONASYNCIODEBUG"):
    val = os.getenv(key)
    if val is not None:
        raw_env.append(f"{key}={val}")





