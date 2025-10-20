# gunicorn_conf.py
import os

# =========================
# App module (fixes ${APP_MODULE} issue)
# =========================
# אם לא מעבירים --wsgi-app מה־CLI, Gunicorn יטעין את זה.
# ניתן להחליף דרך APP_MODULE או APP_MODULE_DEFAULT.
wsgi_app = os.getenv("APP_MODULE", os.getenv("APP_MODULE_DEFAULT", "main:app"))

# =========================
# Bind / workers / class
# =========================
# Bind: address:port (ברירת מחדל: 0.0.0.0:10000)
bind = os.getenv("BIND", f"0.0.0.0:{os.getenv('PORT', '10000')}")

# Workers: מותאם ל-UvicornWorker (async). שמור על מספר קטן בקונטיינרים קטנים.
workers = int(os.getenv("WEB_CONCURRENCY", os.getenv("GWORKERS", "1")))

# Worker class: ניתן להחליף דרך GUNICORN_WORKER_CLASS / GWORKER_CLASS
worker_class = os.getenv(
    "GUNICORN_WORKER_CLASS",
    os.getenv("GWORKER_CLASS", "uvicorn.workers.UvicornWorker"),
)

# חשוב: עם UvicornWorker אין רווח אמיתי מריבוי threads
threads = int(os.getenv("GTHREADS", os.getenv("GUNICORN_THREADS", "1")))

# אופציונלי: מספר חיבורי לקוח בו־זמנית (רלוונטי ל־async workers)
worker_connections = int(os.getenv("GUNICORN_WORKER_CONNECTIONS", "1000"))

# האם לטעון את האפליקציה לפני fork (משפר זיכרון לעיתים; השאר כבוי כברירת מחדל)
preload_app = os.getenv("GUNICORN_PRELOAD", "0").lower() in {"1", "true", "on", "yes"}

# Backlog (תור חיבורים ממתינים ב־listen)
backlog = int(os.getenv("GUNICORN_BACKLOG", "2048"))

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
# ברירת המחדל: STDOUT/STDERR. כדי לכבות accesslog הגדֵר ACCESSLOG="".
_accesslog = os.getenv("ACCESSLOG", "-")
accesslog = _accesslog if _accesslog != "" else None
errorlog = os.getenv("ERRORLOG", "-")
loglevel = os.getenv("LOG_LEVEL", os.getenv("LOGLEVEL", "info")).lower()

# פורמט לוגים (אופציונלי) — אפשר להחליף דרך ENV
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
# אם אתם מאחורי פרוקסי שמגדיר X-Forwarded-Proto, אפשר להכריח HTTPS (אופציונלי)
secure_scheme_headers = {
    "X-Forwarded-Proto": os.getenv("X_FORWARDED_PROTO_HEADER", "https"),
}

# =========================
# Misc
# =========================
# מאפשר reuse_port אם נדרש (ברירת־מחדל: כבוי)
reuse_port = os.getenv("GUNICORN_REUSE_PORT", "0").lower() in {"1", "true", "on", "yes"}

# הגנה מרעשים ב־worker tmp (בעיקר בקונטיינרים)
worker_tmp_dir = os.getenv("GUNICORN_WORKER_TMP_DIR", "/dev/shm")

# הגבלת גודל שורת בקשה/כותרות (אופציונלי; טוב נגד בקשות פתולוגיות)
limit_request_line = int(os.getenv("GUNICORN_LIMIT_REQUEST_LINE", "4094"))
limit_request_fields = int(os.getenv("GUNICORN_LIMIT_REQUEST_FIELDS", "100"))
limit_request_field_size = int(os.getenv("GUNICORN_LIMIT_REQUEST_FIELD_SIZE", "8190"))


