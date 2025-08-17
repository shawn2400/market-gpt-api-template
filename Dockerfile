FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MPLBACKEND=Agg \
    MPLCONFIGDIR=/tmp/matplotlib \
    PYTHONIOENCODING=UTF-8 \
    TZ=UTC

RUN apt-get update -y && apt-get install -y --no-install-recommends \
    ca-certificates curl tini \
    libfreetype6 libpng16-16 fonts-dejavu-core \
    libjpeg62-turbo zlib1g \
 && rm -rf /var/lib/apt/lists/*

RUN useradd -ms /bin/bash appuser
WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN python -m pip install --upgrade pip && pip install -r requirements.txt

COPY . /app

RUN mkdir -p /app/static/reports /app/static/img /tmp/matplotlib \
 && chown -R appuser:appuser /app /tmp/matplotlib

HEALTHCHECK --interval=30s --timeout=5s --retries=5 \
  CMD curl -fsS "http://127.0.0.1:${PORT:-10000}/" || exit 1

USER appuser

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["bash", "-lc", "exec gunicorn main:app \
  -k uvicorn.workers.UvicornWorker \
  --workers 1 \
  --bind 0.0.0.0:${PORT:-10000} \
  --timeout 180 \
  --graceful-timeout 30 \
  --keep-alive 75 \
  --worker-tmp-dir /dev/shm \
  --log-level info"]










