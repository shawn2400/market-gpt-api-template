# gunicorn_conf.py
import os

# =========================
# App module (fixes ${APP_MODULE} issue)
# =========================
# If you DON'T pass the app on the CLI, Gunicorn will use this.
# You can still override via env: APP_MODULE="pkg.module:app"
wsgi_app = os.getenv("APP_MODULE", "algogpt.main:app")

# =========================
# Bind / workers / class
# =========================
bind = os.getenv("BIND", f"0.0.0.0:{os.getenv('PORT', '10000')}")
workers = int(os.getenv("WEB_CONCURRENCY", os.getenv("GWORKERS", "1")))
worker_class = os.getenv(
    "GUNICORN_WORKER_CLASS",
    os.getenv("GWORKER_CLASS", "uvicorn.workers.UvicornWorker"),
)
threads = int(os.getenv("GTHREADS", os.getenv("GUNICORN_THREADS", "1")))

# =========================
# Timeouts / keep-alive
# =========================
graceful_timeout = int(os.getenv("GUNICORN_GRACEFUL_TIMEOUT", os.getenv("GRACEFUL_TIMEOUT", "45")))
timeout = int(os.getenv("GUNICORN_TIMEOUT", os.getenv("TIMEOUT", "180")))
keepalive = int(os.getenv("GUNICORN_KEEPALIVE", os.getenv("KEEPALIVE", "30")))

# =========================
# Recycling (mitigate mem leaks)
# =========================
max_requests = int(os.getenv("GUNICORN_MAX_REQUESTS", "500"))
max_requests_jitter = int(os.getenv("GUNICORN_MAX_REQUESTS_JITTER", "50"))

# =========================
# Logging
# =========================
accesslog = os.getenv("ACCESSLOG", "-") or None  # set "" to disable
errorlog = os.getenv("ERRORLOG", "-")
loglevel = os.getenv("LOG_LEVEL", os.getenv("LOGLEVEL", "info")).lower()

# =========================
# Proxy / forwarded headers
# =========================
forwarded_allow_ips = os.getenv(
    "FORWARDED_ALLOW_IPS",
    os.getenv("GUNICORN_FORWARDED_ALLOW_IPS", "*"),
)

# =========================
# Misc
# =========================
reuse_port = os.getenv("GUNICORN_REUSE_PORT", "0").lower() in {"1", "true", "on", "yes"}
worker_tmp_dir = os.getenv("GUNICORN_WORKER_TMP_DIR", "/dev/shm")





