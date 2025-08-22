# gunicorn_conf.py
import multiprocessing
import os

# Bind port (Render מזריק PORT, ב־Dockerfile כבר הוגדר ברירת מחדל 10000)
bind = f"0.0.0.0:{os.getenv('PORT', '10000')}"

# --- Workers ---
# אם WORKERS=0 → חישוב אוטומטי לפי CPU (2*CPU + 1)
workers_env = int(os.getenv("WORKERS", "0"))
if workers_env > 0:
    workers = workers_env
else:
    workers = multiprocessing.cpu_count() * 2 + 1

# Class של worker (כדי להריץ FastAPI/ASGI עם Uvicorn)
worker_class = "uvicorn.workers.UvicornWorker"

# Timeout (ברירת מחדל 30s – כאן נתתי יותר כי Binance/AI לפעמים איטיים)
timeout = int(os.getenv("TIMEOUT", "60"))

# לוגים ל־stdout (Render אוסף אותם לבד)
accesslog = "-"
errorlog = "-"
loglevel = os.getenv("LOG_LEVEL", "info").lower()

# Max requests (מכריח recycle של workers אחרי X בקשות → מונע memory leaks)
max_requests = int(os.getenv("MAX_REQUESTS", "1000"))
max_requests_jitter = int(os.getenv("MAX_REQUESTS_JITTER", "50"))

# Keep-alive
keepalive = int(os.getenv("KEEPALIVE", "5"))









