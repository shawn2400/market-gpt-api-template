# --- Stage 1: Build with TA-Lib and heavy deps ---
FROM python:3.11-slim as builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# System deps + TA-Lib build
RUN apt-get update -y && apt-get install -y --no-install-recommends \
    ca-certificates curl build-essential gfortran wget \
    libopenblas-dev liblapack-dev \
    libfreetype6-dev libpng-dev libjpeg62-turbo-dev zlib1g-dev \
 && wget -q https://prdownloads.sourceforge.net/ta-lib/ta-lib-0.4.0-src.tar.gz \
 && tar xzf ta-lib-0.4.0-src.tar.gz \
 && cd ta-lib && ./configure --prefix=/usr && make && make install \
 && cd .. && rm -rf ta-lib ta-lib-0.4.0-src.tar.gz \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install python deps into /install
COPY requirements.txt .
RUN python -m pip install --upgrade pip setuptools wheel \
 && pip install --prefix=/install -r requirements.txt

# --- Stage 2: Final lightweight runtime ---
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=10000

# Runtime libs only
RUN apt-get update -y && apt-get install -y --no-install-recommends \
    ca-certificates curl tini libgomp1 \
    libopenblas-dev liblapack-dev \
    libfreetype6 libpng16-16 libjpeg62-turbo zlib1g \
 && rm -rf /var/lib/apt/lists/*

# Copy installed python packages
COPY --from=builder /install /usr/local

# Create app user
RUN useradd -ms /bin/bash appuser
USER appuser

WORKDIR /app

# Copy source code
COPY . /app

# Healthcheck
HEALTHCHECK --interval=30s --timeout=5s --retries=5 \
  CMD curl -fsS "http://127.0.0.1:${PORT}/health" || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["gunicorn", "-c", "gunicorn_conf.py", "main:app"]

























