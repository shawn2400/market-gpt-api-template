# gunicorn_conf.py
import multiprocessing
import os
import logging
import time
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

    server.log.info({"event": "worker_start", "msg": "✅ Gunicorn worker started with JSON logging"})


# --- Custom JSON access log ---
def accesslog_environ(req):
    """עיבוד request dict ל־log אחיד"""
    return {
        "method": req["METHOD"],
        "path": req["RAW_URI"],
        "client_ip": req.get("REMOTE_ADDR"),
        "user_agent": req.get("HTTP_USER_AGENT"),
    }

def accesslog_format(server, req, environ, resp):
    """
    מחזיר JSON string לכל בקשה (במקום טקסט רגיל של Gunicorn)
    """
    start_time = req.start_time if hasattr(req, "start_time") else time.time()
    latency = (time.time() - start_time) * 1000  # ms

    log_data = {
        "event": "http_request",
        "method": req.method,
        "path": req.path,
        "status_code": resp.status,
        "latency_ms": round(latency, 2),
        "client_ip": req.access_log.get("client"),
        "user_agent": req.headers.get("user-agent"),
    }
    import json
    return json.dumps(log_data)




