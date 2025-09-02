# --- Stage 1: Build with TA-Lib C and heavy deps ---
FROM python:3.11-slim AS builder
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

# כלי בנייה + ספריות לפיתוח (לבנייה בלבד)
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

# תלויות ריצה בלבד (לא dev): ספריות BLAS/LAPACK, תמונה, דיאגנוסטיקה קלה
# בדביאן מודרני: libopenblas0-openmp + liblapack3 הן ספריות ריצה מתאימות
RUN apt-get update -y && apt-get install -y --no-install-recommends \
    ca-certificates curl tini \
    libopenblas0-openmp liblapack3 \
    libfreetype6 libpng16-16 libjpeg62-turbo zlib1g \
    procps psmisc \
 && rm -rf /var/lib/apt/lists/*

# ספריות פייתון שנבנו בשלב builder
COPY --from=builder /install /usr/local

# משתמש אפליקטיבי (לא root)
RUN useradd -ms /bin/bash appuser

WORKDIR /app
# חשוב: בשלב הזה אנחנו עדיין root
COPY . /app

# תיקיות והרשאות נחוצות להרצה
RUN set -eux; \
    mkdir -p /app/static /app/logs; \
    chmod 755 /app/static /app/logs || true; \
    chown -R appuser:appuser /app

# סקריפטים אופציונליים: אפשרו exec אם קיימים
RUN test -f /app/prestart.sh && chmod +x /app/prestart.sh || true \
 && test -f /app/health_full.sh && chmod +x /app/health_full.sh || true

# מעבר למשתמש לא־root
USER appuser

# Healthcheck: סקריפט מותאם אם יש, אחרת HTTP /health
HEALTHCHECK --interval=30s --timeout=10s --retries=5 \
  CMD [ -x /app/health_full.sh ] && /app/health_full.sh || curl -fsS "http://127.0.0.1:${PORT}/health" || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]

# הערות ביצועים ובטיחות עומס:
# 1) כדי למנוע משימות רקע כפולות (WS/Keepalive/Manager) — שמרו וורקר אחד.
# 2) ניתן לשלוט דרך משתנה WEB_CONCURRENCY; ברירת מחדל כאן = 1.
# 3) אם אתם מפעילים Gunicorn בפרוסס יחיד, background-tasks ירוצו בדיוק פעם אחת.

ENV WEB_CONCURRENCY=1 \
    GUNICORN_TIMEOUT=120

# prestart (אם קיים) ואז Gunicorn+UvicornWorker
CMD ["bash","-lc","bash /app/prestart.sh 2>/dev/null || true; \
    gunicorn -k uvicorn.workers.UvicornWorker -w ${WEB_CONCURRENCY:-1} \
    -b 0.0.0.0:${PORT:-10000} main:app --timeout ${GUNICORN_TIMEOUT:-120}"]





















