# gunicorn_conf.py
import os

def _env_bool(key: str, default: str = "0") -> bool:
    val = (os.getenv(key, default) or default).strip().lower()
    return val in ("1", "true", "yes", "on")

def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)) or default)
    except Exception:
        return default

def _env_str(key: str, default: str) -> str:
    val = os.getenv(key, default)
    return str(val if val is not None else default)

# ========= Bind =========
_port = _env_int("PORT", 10000)
bind = f"0.0.0.0:{_port}"

# ========= Workers / Threads =========
workers = max(1, _env_int("WEB_CONCURRENCY", _env_int("WORKERS", 1)))
threads = max(1, _env_int("GTHREADS", 1))

# ========= Worker class =========
worker_class = _env_str("GUNICORN_WORKER_CLASS", "uvicorn.workers.UvicornWorker")

# ========= Timeouts / Keep-Alive =========
timeout = max(30, _env_int("GUNICORN_TIMEOUT", _env_int("TIMEOUT", 120)))
graceful_timeout = max(10, _env_int("GUNICORN_GRACEFUL_TIMEOUT", _env_int("GRACEFUL_TIMEOUT", 30)))
keepalive = max(1, _env_int("GUNICORN_KEEPALIVE", _env_int("KEEPALIVE", 5)))

# ========= Logging =========
_guni_access = _env_bool("GUNICORN_ACCESS_LOG", "0")
accesslog = "-" if _guni_access else None
errorlog = "-"
loglevel = (_env_str("LOG_LEVEL", "info") or "info").lower()
access_log_format = '%(h)s %(l)s %(u)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s"'

# ========= Resilience =========
max_requests = max(200, _env_int("GUNICORN_MAX_REQUESTS", _env_int("MAX_REQUESTS", 1000)))
max_requests_jitter = max(0, _env_int("GUNICORN_MAX_REQUESTS_JITTER", _env_int("MAX_REQUESTS_JITTER", 50)))

# ========= Proxy / Forwarded headers =========
forwarded_allow_ips = _env_str("FORWARDED_ALLOW_IPS", "*")
proxy_allow_ips = "*"
if _env_bool("PROXY_PROTOCOL", "0"):
    proxy_protocol = True
secure_scheme_headers = {
    "X-FORWARDED-PROTO": "https",
    "X-FORWARDED-PROTOCOL": "https",
    "X-FORWARDED-SSL": "on",
}

# ========= tmp מהיר (אופציונלי) =========
_worker_tmp_dir = _env_str("WORKER_TMP_DIR", "/dev/shm")
if os.path.isdir(_worker_tmp_dir):
    worker_tmp_dir = _worker_tmp_dir

# ========= Reload (dev) =========
if _env_bool("GUNICORN_RELOAD", "0"):
    reload = True

# ========= Request limits =========
limit_request_line = max(1024, _env_int("LIMIT_REQUEST_LINE", 4094))
limit_request_fields = max(50, _env_int("LIMIT_REQUEST_FIELDS", 100))
limit_request_field_size = max(1024, _env_int("LIMIT_REQUEST_FIELD_SIZE", 8190))

# ========= backlog (optional) =========
_backlog = os.getenv("GUNICORN_BACKLOG")
if _backlog:
    try:
        backlog = max(64, int(_backlog))
    except Exception:
        pass

proc_name = _env_str("PROC_NAME", "algogpt-gunicorn")








