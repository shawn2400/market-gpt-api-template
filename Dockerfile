FROM python:3.11-slim

# --- Env vars ---
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONIOENCODING=UTF-8 \
    PYTHONFAULTHANDLER=1 \
    PYTHONHASHSEED=random \
    MPLBACKEND=Agg \
    MPLCONFIGDIR=/tmp/matplotlib \
    TZ=UTC \
    PATH="/home/appuser/.local/bin:$PATH" \
    PORT=10000

# --- System deps ---
RUN apt-get update -y && apt-get install -y --no-install-recommends \
    ca-certificates curl tini grep procps \
    build-essential gfortran \
    libopenblas-dev liblapack-dev \
    libfreetype6 libpng16-16 fonts-dejavu-core \
    libjpeg62-turbo zlib1g \
    libta-lib0 libta-lib0-dev \
 && rm -rf /var/lib/apt/lists/*

# --- User & workdir ---
RUN useradd -ms /bin/bash appuser
WORKDIR /app

# --- Python deps ---
COPY requirements.txt /app/requirements.txt
RUN python -m pip install --upgrade pip setuptools wheel \
 && pip install --no-cache-dir -r requirements.txt \
 && apt-get purge -y --auto-remove build-essential gfortran \
 && rm -rf /var/lib/apt/lists/*

# --- App source ---
COPY . /app

# --- Static dirs & perms ---
RUN mkdir -p /app/static/reports /app/static/img /tmp/matplotlib \
 && chown -R appuser:appuser /app /tmp/matplotlib

# --- Healthcheck ---
HEALTHCHECK --interval=30s --timeout=5s --retries=5 \
  CMD curl -fsS "http://127.0.0.1:${PORT}/health" || exit 1

# --- Switch user ---
USER appuser

# --- Entrypoint & CMD ---
ENTRYPOINT ["/usr/bin/tini", "--"]

CMD ["gunicorn", "-k", "uvicorn.workers.UvicornWorker", "-w", "2", "-b", "0.0.0.0:10000", "main:app"]
















