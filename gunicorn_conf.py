# gunicorn_conf.py
import multiprocessing
import os

# Workers
workers = int(os.getenv("WORKERS", multiprocessing.cpu_count() * 2 + 1))
worker_class = "uvicorn.workers.UvicornWorker"

# Binding
bind = f"0.0.0.0:{os.getenv('PORT', '10000')}"

# Timeouts
timeout = 120
graceful_timeout = 30
keepalive = 5

# Worker recycling
max_requests = 2000
max_requests_jitter = 200
worker_tmp_dir = "/dev/shm"

# Logging
loglevel = "info"
accesslog = "-"
errorlog = "-"

