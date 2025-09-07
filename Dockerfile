# --- Stage 1: Builder (pip install לשכבת /install) ---
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# כלים לבניה (במקרה ויהיה צורך בגלגל שמתקמפל מקומית; לרוב נקבל manylinux wheels)
RUN apt-get update -y && apt-get install -y --no-install-recommends \
    ca-certificates curl build-essential \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./requirements.txt

# שדרוג pip/setuptools + התקנת תלויות אל /install (יועתקו לשלב הריצה)
RUN python -m pip install --upgrade pip setuptools wheel \
 && pip install --prefix=/install --no-cache-dir -r requirements.txt

# --- Stage 2: Runtime ---
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=10000

# ספריות ריצה דקיקות ל-numpy/scipy/matplotlib ועוד
RUN apt-get update -y && apt-get install -y --no-install-recommends \
    ca-certificates curl tini \
    libopenblas0-openmp liblapack3 \
    libfreetype6 libpng16-16 libjpeg62-turbo zlib1g \
    procps psmisc \
 && rm -rf /var/lib/apt/lists/*

# שכבת הפייתון שכבר מותקנת מה-builder
COPY --from=builder /install /usr/local

# יצירת משתמש לא-רוט
RUN useradd -ms /bin/bash appuser

WORKDIR /app
COPY . /app

# תיקיות נפוצות + הרשאות
RUN set -eux; \
    mkdir -p /app/static /app/logs; \
    chmod 755 /app/static /app/logs || true; \
    chown -R appuser:appuser /app

# סקריפטים אופציונליים אם קיימים
RUN test -f /app/prestart.sh && chmod +x /app/prestart.sh || true \
 && test -f /app/health_full.sh && chmod +x /app/health_full.sh || true

USER appuser

# Healthcheck: קודם health_full.sh אם קיים, אחרת /health
HEALTHCHECK --interval=30s --timeout=10s --retries=5 \
  CMD [ -x /app/health_full.sh ] && /app/health_full.sh || curl -fsS "http://127.0.0.1:${PORT}/health" || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]

# פרמטרים נוחים לריצה בענן
ENV WEB_CONCURRENCY=1 \
    GUNICORN_TIMEOUT=120

# הרצת השרת (prestart אם קיים)
CMD ["bash","-lc","bash /app/prestart.sh 2>/dev/null || true; \
    gunicorn -k uvicorn.workers.UvicornWorker -w ${WEB_CONCURRENCY:-1} \
    -b 0.0.0.0:${PORT:-10000} main:app --timeout ${GUNICORN_TIMEOUT:-120}"]
























