import os

# =========================
# Bind / workers / class
# =========================
# פורט לפי PORT, כתובת לפי BIND (ברירת מחדל: 0.0.0.0)
bind = os.getenv("BIND", f"0.0.0.0:{os.getenv('PORT', '10000')}")

# מספר וורקרים: מותאם ל־UvicornWorker (async)
workers = int(os.getenv("WEB_CONCURRENCY", os.getenv("GWORKERS", "1")))
worker_class = os.getenv("GWORKER_CLASS", "uvicorn.workers.UvicornWorker")

# חשוב: עם UvicornWorker אין תועלת בריבוי threads
threads = int(os.getenv("GTHREADS", "1"))

# =========================
# Timeouts / keep-alive
# =========================
# תואם למשתנים שהגדרת ב־Render.yaml
graceful_timeout = int(os.getenv("GUNICORN_GRACEFUL_TIMEOUT", os.getenv("GRACEFUL_TIMEOUT", "30")))
timeout = int(os.getenv("GUNICORN_TIMEOUT", os.getenv("TIMEOUT", "120")))
keepalive = int(os.getenv("GUNICORN_KEEPALIVE", os.getenv("KEEPALIVE", "30")))

# =========================
# Recycling (להקטנת דליפות זיכרון)
# =========================
max_requests = int(os.getenv("GUNICORN_MAX_REQUESTS", "500"))
max_requests_jitter = int(os.getenv("GUNICORN_MAX_REQUESTS_JITTER", "50"))

# =========================
# Logging
# =========================
# ברירת המחדל: STDOUT/STDERR. ניתן לכבות accesslog ע"י ACCESSLOG="".
accesslog = os.getenv("ACCESSLOG", "-")
errorlog = os.getenv("ERRORLOG", "-")

# רמת לוג: לוקח קודם LOG_LEVEL (שהוגדר ב־env)
loglevel = os.getenv("LOG_LEVEL", os.getenv("LOGLEVEL", "info")).lower()

# =========================
# Proxy / forwarded headers
# =========================
forwarded_allow_ips = os.getenv("FORWARDED_ALLOW_IPS", "*")

# =========================
# Misc toggles (אופציונלי)
# =========================
# מאפשר reuse_port אם נדרש (ברירת־מחדל: כבוי)
reuse_port = os.getenv("GUNICORN_REUSE_PORT", "0").lower() in {"1", "true", "on", "yes"}

# הגנה מרעשים ב־worker tmp (בעיקר בקונטיינרים)
worker_tmp_dir = os.getenv("GUNICORN_WORKER_TMP_DIR", "/dev/shm")








