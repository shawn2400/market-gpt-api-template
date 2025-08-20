# gunicorn_conf.py
import multiprocessing
import os

# קח לוגיקה: (מספר ליבות * 2) + 1
workers = int(os.getenv("WORKERS", (multiprocessing.cpu_count() * 2) + 1))

# Bind
bind = f"0.0.0.0:{os.getenv('PORT', '10000')}"

# Worker class
worker_class = "uvicorn.workers.UvicornWorker"

# Timeout settings
timeout = 180
graceful_timeout = 30
keepalive = 10

# Stability
max_requests = 2000
max_requests_jitter = 200
worker_tmp_dir = "/dev/shm"

# Logging
log_level = os.getenv("LOG_LEVEL", "info")
