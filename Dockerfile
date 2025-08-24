FROM python:3.11-slim

# --- Env vars ---
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONIOENCODING=UTF-8 \
    PYTHONFAULTHANDLER=1 \
    PYTHONHASHSEED=random \
    TZ=UTC \
    PORT=10000

# --- System deps ---
RUN apt-get update -y && apt-get install -y --no-install-recommends \
    ca-certificates curl tini grep procps \
    build-essential gfortran wget make \
    libopenblas-dev liblapack-dev \
    libfreetype6 libpng-dev fonts-dejavu-core \
    libjpeg62-turbo-dev zlib1g-dev \
 && rm -rf /var/lib/apt/lists/*

# --- Build TA-Lib from source ---
WORKDIR /tmp
RUN wget http://prdownloads.sourceforge.net/ta-lib/ta-lib-0.4.0-src.tar.gz \
 && tar -xvzf ta-lib-0.4.0-src.tar.gz \
 && cd ta-lib && ./configure --prefix=/usr && make && make install \
 && cd .. && rm -rf ta-lib*

# --- User & workdir ---
RUN useradd -ms /bin/bash appuser
WORKDIR /app

# --- Python deps ---
COPY requirements.txt /app/requirements.txt
RUN python -m pip install --upgrade pip setuptools wheel \
 && pip install --no-cache-dir -r requirements.txt \
 && apt-get purge -y --auto-remove build-essential gfortran wget make \
 && rm -rf /var/lib/apt/lists/* /root/.cache

# --- App source ---
COPY . /app

# --- Static dirs ---
RUN mkdir -p /app/static /tmp \
 && chown -R appuser:appuser /app /tmp

# --- Healthcheck ---
HEALTHCHECK --interval=30s --timeout=5s --retries=5 \
  CMD curl -fsS "http://127.0.0.1:${PORT}/health" || exit 1

# --- Switch user ---
USER appuser

# --- Entrypoint & CMD ---
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["gunicorn", "-c", "gunicorn_conf.py", "main:app"]























