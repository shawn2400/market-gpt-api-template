# gunicorn_conf.py
import os

# =========================
# Bind / workers / class
# =========================
# Bind: כתובת:פורט (ברירת מחדל: 0.0.0.0:10000)
bind = os.getenv("BIND", f"0.0.0.0:{os.getenv('PORT', '10000')}")

# Workers: מותאם ל-UvicornWorker (async)
workers = int(os.getenv("WEB_CONCURRENCY", os.getenv("GWORKERS", "1")))

# Worker class: ניתן להחליף דרך GUNICORN_WORKER_CLASS / GWORKER_CLASS
worker_class = os.getenv(
    "GUNICORN_WORKER_CLASS",
    os.getenv("GWORKER_CLASS", "uvicorn.workers.UvicornWorker")
)

# חשוב: עם UvicornWorker אין רווח אמיתי בריבוי threads
threads = int(os.getenv("GTHREADS", os.getenv("GUNICORN_THREADS", "1")))

# =========================
# Timeouts / keep-alive
# =========================
# תואם ל-env ב-render.yaml
graceful_timeout = int(os.getenv("GUNICORN_GRACEFUL_TIMEOUT", os.getenv("GRACEFUL_TIMEOUT", "45")))
timeout = int(os.getenv("GUNICORN_TIMEOUT", os.getenv("TIMEOUT", "180")))
keepalive = int(os.getenv("GUNICORN_KEEPALIVE", os.getenv("KEEPALIVE", "30")))

# =========================
# Recycling (להקטנת דליפות זיכרון)
# =========================
max_requests = int(os.getenv("GUNICORN_MAX_REQUESTS", "500"))
max_requests_jitter = int(os.getenv("GUNICORN_MAX_REQUESTS_JITTER", "50"))

# =========================
# Logging
# =========================
# ברירת המחדל: STDOUT/STDERR. לכבות accesslog ע"י ACCESSLOG="". 
accesslog = os.getenv("ACCESSLOG", "-")
errorlog = os.getenv("ERRORLOG", "-")
loglevel = os.getenv("LOG_LEVEL", os.getenv("LOGLEVEL", "info")).lower()

# =========================
# Proxy / forwarded headers
# =========================
forwarded_allow_ips = os.getenv(
    "FORWARDED_ALLOW_IPS",
    os.getenv("GUNICORN_FORWARDED_ALLOW_IPS", "*")
)

# =========================
# Misc
# =========================
# מאפשר reuse_port אם נדרש (ברירת־מחדל: כבוי)
reuse_port = os.getenv("GUNICORN_REUSE_PORT", "0").lower() in {"1", "true", "on", "yes"}

# הגנה מרעשים ב־worker tmp (בעיקר בקונטיינרים)
worker_tmp_dir = os.getenv("GUNICORN_WORKER_TMP_DIR", "/dev/shm")






