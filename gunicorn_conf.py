# gunicorn_conf.py
import os
import sys
import logging

# =========================
# Logging Setup (CRITICAL for debugging production crashes)
# =========================
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(process)d] [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

# =========================
# App module (fixes ${APP_MODULE} issue)
# =========================
# אם לא מעבירים --wsgi-app מה־CLI, Gunicorn יטעין את זה.
# ניתן להחליף דרך APP_MODULE או APP_MODULE_DEFAULT.
wsgi_app = os.getenv("APP_MODULE", os.getenv("APP_MODULE_DEFAULT", "main:app"))
logger.info(f"🚀 Loading app: {wsgi_app}")

# =========================
# Bind / workers / class
# =========================
bind = os.getenv("BIND", f"0.0.0.0:{os.getenv('PORT', '5000')}")
workers = int(os.getenv("WEB_CONCURRENCY", os.getenv("GWORKERS", "1")))
worker_class = os.getenv(
    "GUNICORN_WORKER_CLASS",
    os.getenv("GWORKER_CLASS", "uvicorn.workers.UvicornWorker"),
)
threads = int(os.getenv("GTHREADS", os.getenv("GUNICORN_THREADS", "1")))
worker_connections = int(os.getenv("GUNICORN_WORKER_CONNECTIONS", "1000"))
preload_app = os.getenv("GUNICORN_PRELOAD", "0").lower() in {"1", "true", "on", "yes"}
backlog = int(os.getenv("GUNICORN_BACKLOG", "2048"))

logger.info(f"📡 Binding to: {bind}")
logger.info(f"👷 Workers: {workers} | Worker class: {worker_class}")

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
_accesslog = os.getenv("ACCESSLOG", "-")
accesslog = _accesslog if _accesslog != "" else None  # set ACCESSLOG="" to disable
errorlog = os.getenv("ERRORLOG", "-")
loglevel = os.getenv("LOG_LEVEL", os.getenv("LOGLEVEL", "info")).lower()
access_log_format = os.getenv(
    "GUNICORN_ACCESS_LOG_FORMAT",
    '%(h)s %(l)s %(u)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(L)s'
)

# =========================
# Proxy / forwarded headers
# =========================
forwarded_allow_ips = os.getenv(
    "FORWARDED_ALLOW_IPS",
    os.getenv("GUNICORN_FORWARDED_ALLOW_IPS", "*"),
)
secure_scheme_headers = {
    "X-Forwarded-Proto": os.getenv("X_FORWARDED_PROTO_HEADER", "https"),
}

# =========================
# Misc
# =========================
reuse_port = os.getenv("GUNICORN_REUSE_PORT", "1").lower() in {"1", "true", "on", "yes"}  # Changed default to True for better performance
worker_tmp_dir = os.getenv("GUNICORN_WORKER_TMP_DIR", "/dev/shm")
limit_request_line = int(os.getenv("GUNICORN_LIMIT_REQUEST_LINE", "4094"))
limit_request_fields = int(os.getenv("GUNICORN_LIMIT_REQUEST_FIELDS", "100"))
limit_request_field_size = int(os.getenv("GUNICORN_LIMIT_REQUEST_FIELD_SIZE", "8190"))

# =========================
# Lifecycle Hooks (CRITICAL for debugging crashes)
# =========================
def on_starting(server):
    """Called just before the master process is initialized."""
    logger.info("🎬 Gunicorn master process starting...")
    logger.info(f"📊 Configuration: workers={workers}, timeout={timeout}s, bind={bind}")

def on_reload(server):
    """Called to recycle workers during a reload via SIGHUP."""
    logger.info("🔄 Gunicorn reloading workers...")

def when_ready(server):
    """Called just after the server is started."""
    logger.info("✅ Gunicorn server is ready! Listening on %s", server.address)

def pre_fork(server, worker):
    """Called just before a worker is forked."""
    logger.info(f"👶 Forking worker {worker.pid}...")

def post_fork(server, worker):
    """Called just after a worker has been forked."""
    logger.info(f"✅ Worker {worker.pid} forked successfully")

def pre_exec(server):
    """Called just before a new master process is forked."""
    logger.info("🔧 Gunicorn master re-exec...")

def worker_int(worker):
    """Called when a worker receives an INT or QUIT signal."""
    logger.warning(f"⚠️ Worker {worker.pid} received INT/QUIT signal")

def worker_abort(worker):
    """Called when a worker is aborted (timeout)."""
    logger.error(f"❌ Worker {worker.pid} ABORTED (timeout or crash)!")

def pre_request(worker, req):
    """Called just before a worker processes the request."""
    pass  # Too verbose, disable by default

def post_request(worker, req, environ, resp):
    """Called after a worker processes the request."""
    pass  # Too verbose, disable by default

def worker_exit(server, worker):
    """Called just after a worker has been exited."""
    logger.warning(f"👋 Worker {worker.pid} exited")

def child_exit(server, worker):
    """Called just after a worker has been exited, in the master process."""
    logger.warning(f"💀 Worker {worker.pid} child process exited")

def on_exit(server):
    """Called just before exiting Gunicorn."""
    logger.info("👋 Gunicorn server shutting down...")
