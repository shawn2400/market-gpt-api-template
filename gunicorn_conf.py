# gunicorn_conf.py
import os

# ========= Bind =========
bind = f"0.0.0.0:{int(os.getenv('PORT', '10000') or '10000')}"

# ========= Workers / Threads =========
# לוקח מ-WEB_CONCURRENCY אם יש, אחרת WORKERS, אחרת 1
workers = int(os.getenv("WEB_CONCURRENCY") or os.getenv("WORKERS", "1") or "1")

# מספר threads רלוונטי רק אם משתמשים ב-gthread; נשאיר למקרה הצורך
threads = int(os.getenv("GTHREADS", "1") or "1")

# ========= Worker class =========
# uvicorn worker (asyncio) – מומלץ ל-FastAPI
worker_class = os.getenv("GUNICORN_WORKER_CLASS", "uvicorn.workers.UvicornWorker")

# ========= Timeouts / Keep-Alive =========
timeout = int(os.getenv("GUNICORN_TIMEOUT", os.getenv("TIMEOUT", "120")) or "120")
graceful_timeout = int(os.getenv("GUNICORN_GRACEFUL_TIMEOUT", os.getenv("GRACEFUL_TIMEOUT", "30")) or "30")
keepalive = int(os.getenv("GUNICORN_KEEPALIVE", os.getenv("KEEPALIVE", "5")) or "5")

# ========= Logging =========
accesslog = "-"
errorlog = "-"
loglevel = (os.getenv("LOG_LEVEL", "info") or "info").lower()
access_log_format = '%(h)s %(l)s %(u)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s"'

# ========= Resilience (מניעת דליפות) =========
max_requests = int(os.getenv("MAX_REQUESTS", "1000") or "1000")
max_requests_jitter = int(os.getenv("MAX_REQUESTS_JITTER", "50") or "50")

# ========= Proxy / Forwarded headers =========
# Render / פרוקסי – לאפשר קריאת X-Forwarded-* לצורך IP/Proto
forwarded_allow_ips = os.getenv("FORWARDED_ALLOW_IPS", "*")
# proxy_allow_ips היסטורי; לא מזיק להשאיר תואם לאחור
proxy_allow_ips = "*"

# ========= משאבים / tmp מהיר (אופציונלי) =========
# שימוש ב-/dev/shm אם קיים (פחות IO על דיסק, מועיל לחלק מהספריות)
worker_tmp_dir = os.getenv("WORKER_TMP_DIR", "/dev/shm")

# ========= Uvicorn env ירושה ל-workers =========
# raw_env מאפשר הזרקת משתני סביבה ישירות לוורקר (uvicorn משתמש בהם ללוגים/דיבוג)
raw_env = []
for key in ("UVICORN_LOG_LEVEL", "UVICORN_ACCESS_LOG", "PYTHONASYNCIODEBUG"):
    val = os.getenv(key)
    if val is not None:
        raw_env.append(f"{key}={val}")

# ========= פיצ'רים אופציונליים (דרך ENV) =========
# אפשר להפעיל reload בסביבת פיתוח: GUNICORN_RELOAD=1
if (os.getenv("GUNICORN_RELOAD", "0") or "0").lower() in ("1", "true", "yes", "on"):
    reload = True

# אפשר להגביל גודל שורת בקשה/כותרות אם יש צורך (הגיוני לשירותים ציבוריים)
limit_request_line = int(os.getenv("LIMIT_REQUEST_LINE", "4094") or "4094")
limit_request_fields = int(os.getenv("LIMIT_REQUEST_FIELDS", "100") or "100")
limit_request_field_size = int(os.getenv("LIMIT_REQUEST_FIELD_SIZE", "8190") or "8190")

# ========= שם תהליך (לנוחות ניטור) =========
proc_name = os.getenv("PROC_NAME", "algogpt-gunicorn")






