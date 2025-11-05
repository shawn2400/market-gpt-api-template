# ============================
# Stage 1: builder
# ============================
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8

RUN apt-get update -y && apt-get install -y --no-install-recommends \
    build-essential curl ca-certificates git && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN python -m pip install --upgrade pip setuptools wheel && \
    pip install --prefix=/install --no-cache-dir -r requirements.txt && \
    pip check

# ============================
# Stage 2: runtime
# ============================
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LANG=C.UTF-8

# העתקת התלויות מה-builder
COPY --from=builder /install /usr/local

# קוד האפליקציה
WORKDIR /app
COPY . .

# ברירת מחדל ל-FastAPI + Gunicorn+UvicornWorker
ENV PORT=8000 \
    WORKERS=2 \
    WEB_CONCURRENCY=2

EXPOSE 8000

# אם נקודת הכניסה שלך היא main.py עם app=FastAPI(...)
# שנה לפי שם המודול שלך
CMD ["bash", "-lc", "exec gunicorn main:app -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:${PORT} --workers ${WEB_CONCURRENCY} --timeout 120"]
