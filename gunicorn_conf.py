# gunicorn_conf.py
import multiprocessing
import os

# Bind
bind = f"0.0.0.0:{os.getenv('PORT', '10000')}"

# --- Workers ---
workers_env = os.getenv("WORKERS")
if workers_env:
    workers = int(workers_env)
else:
    # ברירת־מחדל שמרנית לשרתים קטנים (~2GB RAM): שומר יציבות
    workers = 2

worker_class = "uvicorn.workers.UvicornWorker"

# --- Timeouts ---
timeout = int(os.getenv("TIMEOUT", "60"))
graceful_timeout = int(os.getenv("GRACEFUL_TIMEOUT", "30"))
keepalive = int(os.getenv("KEEPALIVE", "10"))

# --- Logs ---
accesslog = "-"
errorlog = "-"
loglevel = os.getenv("LOG_LEVEL", "info").lower()
# לוג גישה קומפקטי ושימושי
access_log_format = '%(h)s %(l)s %(u)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s"'

# --- Recycle workers (מניעת דליפות זיכרון) ---
max_requests = int(os.getenv("MAX_REQUESTS", "1000"))
max_requests_jitter = int(os.getenv("MAX_REQUESTS_JITTER", "50"))

# --- Misc ---
capture_output = True
forwarded_allow_ips = os.getenv("FORWARDED_ALLOW_IPS", "*")

# מעביר משתני סביבה רלוונטיים ל־Uvicorn workers (אם הוגדרו בסביבה)
_raw_env = []
for key in ("UVICORN_LOG_LEVEL", "UVICORN_ACCESS_LOG", "PYTHONASYNCIODEBUG"):
    val = os.getenv(key)
    if val is not None:
        _raw_env.append(f"{key}={val}")
raw_env = _raw_env










