# --- Stage 1: Build with TA-Lib C and heavy deps ---
FROM python:3.11-slim as builder
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

RUN apt-get update -y && apt-get install -y --no-install-recommends \
    ca-certificates curl build-essential gfortran wget \
    libopenblas-dev liblapack-dev libfreetype6-dev libpng-dev \
    libjpeg62-turbo-dev zlib1g-dev \
 && wget -q https://prdownloads.sourceforge.net/ta-lib/ta-lib-0.4.0-src.tar.gz \
 && tar xzf ta-lib-0.4.0-src.tar.gz \
 && cd ta-lib && ./configure --prefix=/usr && make && make install \
 && cd .. && rm -rf ta-lib ta-lib-0.4.0-src.tar.gz \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN python -m pip install --upgrade pip setuptools wheel \
 && pip install --prefix=/install --no-cache-dir -r requirements.txt


# --- Stage 2: Final runtime ---
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=10000

# runtime deps (+ כלי דיאגנוסטיקה קלים)
RUN apt-get update -y && apt-get install -y --no-install-recommends \
    ca-certificates curl tini libgomp1 \
    libopenblas-dev liblapack-dev \
    libfreetype6 libpng16-16 libjpeg62-turbo zlib1g \
    procps psmisc \
 && rm -rf /var/lib/apt/lists/*

# ספריות פייתון שנבנו בשלב builder
COPY --from=builder /install /usr/local

# משתמש אפליקטיבי
RUN useradd -ms /bin/bash appuser

# נעתיק את האפליקציה, נוודא תיקיות ו"בעלות" לפני מעבר ל-user
WORKDIR /app
# חשוב: בשלב הזה אנחנו עדיין root
COPY . /app

# צור/תקן הרשאות לתיקיות דרושות להרצה
RUN set -eux; \
    mkdir -p /app/static /app/logs; \
    chmod 755 /app/static; \
    chmod 755 /app/logs || true; \
    chown -R appuser:appuser /app

# אם יש סקריפטים — תן להם exec (עדיין root פה)
RUN test -f /app/prestart.sh && chmod +x /app/prestart.sh || true \
 && test -f /app/health_full.sh && chmod +x /app/health_full.sh || true

# עכשיו עוברים למשתמש האפליקטיבי
USER appuser

# Healthcheck: סקריפט אם קיים, אחרת HTTP fallback
HEALTHCHECK --interval=30s --timeout=10s --retries=5 \
  CMD [ -x /app/health_full.sh ] && /app/health_full.sh || curl -fsS "http://127.0.0.1:${PORT}/health" || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]

# נפעיל prestart דרך bash (לא תלוי ב-exec bit) ואז gunicorn
CMD ["bash","-lc","bash /app/prestart.sh && gunicorn -k uvicorn.workers.UvicornWorker -w ${WEB_CONCURRENCY:-2} -b 0.0.0.0:${PORT:-10000} main:app --timeout ${GUNICORN_TIMEOUT:-120}"]























