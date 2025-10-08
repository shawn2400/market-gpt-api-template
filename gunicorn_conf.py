# gunicorn_conf.py
import os

bind = f"0.0.0.0:{os.getenv('PORT', '10000')}"
workers = int(os.getenv("WORKERS", "2"))
worker_class = "uvicorn.workers.UvicornWorker"

timeout = int(os.getenv("TIMEOUT", "60"))
graceful_timeout = int(os.getenv("GRACEFUL_TIMEOUT", "30"))
keepalive = int(os.getenv("KEEPALIVE", "10"))

accesslog = "-"
errorlog = "-"
loglevel = os.getenv("LOG_LEVEL", "info").lower()
access_log_format = '%(h)s %(l)s %(u)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s"'

max_requests = int(os.getenv("MAX_REQUESTS", "1000"))
max_requests_jitter = int(os.getenv("MAX_REQUESTS_JITTER", "50"))

capture_output = True
forwarded_allow_ips = os.getenv("FORWARDED_ALLOW_IPS", "*")

raw_env = []
for key in ("UVICORN_LOG_LEVEL", "UVICORN_ACCESS_LOG", "PYTHONASYNCIODEBUG"):
    val = os.getenv(key)
    if val is not None:
        raw_env.append(f"{key}={val}")









