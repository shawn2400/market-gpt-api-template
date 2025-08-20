# gunicorn_conf.py
import multiprocessing
import os
import logging
from utils.json_logger import JsonFormatter

# --- Workers ---
workers = int(os.getenv("WORKERS", multiprocessing.cpu_count() * 2 + 1))
worker_class = "uvicorn.workers.UvicornWorker"

# --- Binding ---
bind = f"0.0.0.0:{os.getenv('PORT', '10000')}"

# --- Timeouts ---
timeout = 120
graceful_timeout = 30
keepalive = 5

# --- Worker recycling ---
max_requests = 2000
max_requests_jitter = 200
worker_tmp_dir = "/dev/shm"

# --- Logging ---
loglevel = "info"
accesslog = "-"  # STDOUT
errorlog = "-"   # STDERR

# --- JSON Log setup ---
def post_fork(server, worker):
    """הגדרה אחידה ל־JSON logs גם ל־Gunicorn וגם ל־Uvicorn"""
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)

    server.log.info("✅ Gunicorn worker started with JSON logging")



