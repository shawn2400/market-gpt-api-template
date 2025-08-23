# gunicorn_conf.py
import multiprocessing
import os

bind = f"0.0.0.0:{os.getenv('PORT', '10000')}"

# --- Workers ---
workers_env = int(os.getenv("WORKERS", "0"))
if workers_env > 0:
    workers = workers_env
else:
    # 🔹 2GB → מספיק 2 workers (שומרים על יציבות)
    workers = 2

worker_class = "uvicorn.workers.UvicornWorker"
timeout = int(os.getenv("TIMEOUT", "60"))

# לוגים ל־stdout
accesslog = "-"
errorlog = "-"
loglevel = os.getenv("LOG_LEVEL", "info").lower()

# recycle workers → מונע memory leaks
max_requests = int(os.getenv("MAX_REQUESTS", "1000"))
max_requests_jitter = int(os.getenv("MAX_REQUESTS_JITTER", "50"))

keepalive = int(os.getenv("KEEPALIVE", "5"))










