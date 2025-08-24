# --- Stage 1: Build with TA-Lib and heavy deps ---
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DEBIAN_FRONTEND=noninteractive

# System deps + TA-Lib build
# (משתיק הודעות apt לא מהותיות ללוגים ע"י ניתוב ל-/dev/null)
RUN apt-get update -y >/dev/null 2>&1 && \
    apt-get install -y --no-install-recommends \
      ca-certificates curl build-essential gfortran wget \
      libopenblas-dev liblapack-dev \
      libfreetype6-dev libpng-dev libjpeg62-turbo-dev zlib1g-dev \
      xz-utils \
    >/dev/null 2>&1 && \
    wget -q https://prdownloads.sourceforge.net/ta-lib/ta-lib-0.4.0-src.tar.gz && \
    tar xzf ta-lib-0.4.0-src.tar.gz && \
    cd ta-lib && ./configure --prefix=/usr >/dev/null 2>&1 && \
    make -j"$(nproc)"  >/dev/null 2>&1 && \
    make install        >/dev/null 2>&1 && \
    cd .. && rm -rf ta-lib ta-lib-0.4.0-src.tar.gz && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install python deps into /install (נקי מקאש)
COPY requirements.txt ./
RUN python -m pip install --upgrade pip setuptools wheel >/dev/null 2>&1 && \
    pip install --prefix=/install --no-cache-dir -r requirements.txt

# --- Stage 2: Final lightweight runtime ---
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=10000 \
    DEBIAN_FRONTEND=noninteractive

# Runtime libs only
RUN apt-get update -y >/dev/null 2>&1 && \
    apt-get install -y --no-install-recommends \
      ca-certificates curl tini libgomp1 \
      libopenblas-dev liblapack-dev \
      libfreetype6 libpng16-16 libjpeg62-turbo zlib1g \
    >/dev/null 2>&1 && \
    rm -rf /var/lib/apt/lists/*

# Copy installed python packages from builder
COPY --from=builder /install /usr/local

# Create non-root user
RUN useradd -ms /bin/bash appuser
USER appuser

WORKDIR /app

# Copy app source (ללא .env – ר’ .dockerignore)
COPY . /app

# Healthcheck (נדרש curl שכבר מותקן)
HEALTHCHECK --interval=30s --timeout=5s --retries=5 \
  CMD curl -fsS "http://127.0.0.1:${PORT}/health" || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["gunicorn", "-c", "gunicorn_conf.py", "main:app"]


























