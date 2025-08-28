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

# runtime deps + minimal debug tools
RUN apt-get update -y && apt-get install -y --no-install-recommends \
    ca-certificates curl tini libgomp1 \
    libopenblas-dev liblapack-dev \
    libfreetype6 libpng16-16 libjpeg62-turbo zlib1g \
    procps psmisc \
 && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local

# create non-root user
RUN useradd -ms /bin/bash appuser
USER appuser
WORKDIR /app

# copy app
COPY . /app

# ensure prestart.sh & health_full.sh executable
RUN [ -f /app/prestart.sh ] && chmod +x /app/prestart.sh || true
RUN [ -f /app/health_full.sh ] && chmod +x /app/health_full.sh || true

# Healthcheck uses health_full.sh
HEALTHCHECK --interval=30s --timeout=10s --retries=5 \
  CMD /app/health_full.sh || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["bash","-lc","/app/prestart.sh && gunicorn -k uvicorn.workers.UvicornWorker -w ${WEB_CONCURRENCY:-2} -b 0.0.0.0:${PORT:-10000} main:app --timeout ${GUNICORN_TIMEOUT:-120}"]


























