# --- Stage 1: Build with TA-Lib and heavy deps ---
FROM python:3.11-slim as builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_NO_BUILD_ISOLATION=1

# System deps + build TA-Lib C library
RUN apt-get update -y && apt-get install -y --no-install-recommends \
    ca-certificates curl build-essential gfortran wget \
    libopenblas-dev liblapack-dev \
    libfreetype6-dev libpng-dev libjpeg62-turbo-dev zlib1g-dev \
 && wget -q https://prdownloads.sourceforge.net/ta-lib/ta-lib-0.4.0-src.tar.gz \
 && tar xzf ta-lib-0.4.0-src.tar.gz \
 && cd ta-lib && ./configure --prefix=/usr && make -j"$(nproc)" && make install \
 && cd .. && rm -rf ta-lib ta-lib-0.4.0-src.tar.gz \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# נועלים NumPy 1.26.4 כדי למנוע קונפליקטים
RUN python -m pip install --upgrade pip setuptools wheel \
 && pip install --prefix=/install --no-cache-dir "numpy==1.26.4"

# מעטפת Python של TA-Lib מול הספרייה שב-/usr
RUN TA_LIBRARY_PATH=/usr/lib TA_INCLUDE_PATH=/usr/include \
    pip install --prefix=/install --no-cache-dir --no-build-isolation "TA-Lib==0.4.28"

# שאר התלויות (בלי TA-Lib בקובץ)
COPY requirements.txt .
RUN sed -i '/^[Tt][Aa]-[Ll]ib.*/d' requirements.txt \
 && pip install --prefix=/install --no-cache-dir -r requirements.txt

# --- Stage 2: Final lightweight runtime ---
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=10000

# Runtime libs בלבד
RUN apt-get update -y && apt-get install -y --no-install-recommends \
    ca-certificates curl tini libgomp1 \
    libopenblas-dev liblapack-dev \
    libfreetype6 libpng16-16 libjpeg62-turbo zlib1g \
 && rm -rf /var/lib/apt/lists/*

# חבילות Python + libta_lib.so מה־builder
COPY --from=builder /install /usr/local
COPY --from=builder /usr/lib/libta_lib.so* /usr/lib/
COPY --from=builder /usr/bin/ta-lib-config /usr/bin/

# non-root
RUN useradd -ms /bin/bash appuser
USER appuser

WORKDIR /app
COPY . /app

HEALTHCHECK --interval=30s --timeout=5s --retries=5 \
  CMD curl -fsS "http://127.0.0.1:${PORT}/health" || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["gunicorn", "-c", "gunicorn_conf.py", "main:app"]






























