# gunicorn_conf.py
import multiprocessing
import os

# Port injected by Render (ב־Dockerfile הוגדר כבר PORT=10000)
bind = f"0.0.0.0:{os.getenv('PORT', '10000')}"

# מספר workers - לפי WORKERS או לפי CPU
workers = int(os.getenv("WORKERS", str(multiprocessing.cpu_count() * 2 + 1)))

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








