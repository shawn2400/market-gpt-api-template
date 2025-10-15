import os

# Basic sane defaults; can be overridden via env
bind = os.getenv("BIND", f"0.0.0.0:{os.getenv('PORT', '10000')}")
workers = int(os.getenv("GWORKERS", os.getenv("WEB_CONCURRENCY", "1")))
worker_class = os.getenv("GWORKER_CLASS", "uvicorn.workers.UvicornWorker")

# IMPORTANT: UvicornWorker works best with threads=1
threads = int(os.getenv("GTHREADS", "1"))

# Optional tuning
graceful_timeout = int(os.getenv("GRACEFUL_TIMEOUT", "30"))
timeout = int(os.getenv("TIMEOUT", "30"))
keepalive = int(os.getenv("KEEPALIVE", "5"))

accesslog = os.getenv("ACCESSLOG", "-")
errorlog = os.getenv("ERRORLOG", "-")
loglevel = os.getenv("LOGLEVEL", os.getenv("LOG_LEVEL", "info"))

# Forwarded proto/for headers (when behind proxy)
forwarded_allow_ips = os.getenv("FORWARDED_ALLOW_IPS", "*")








