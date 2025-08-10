# ---- Base ----
FROM python:3.11-slim

# System settings
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8000

# (Optional) Timezone - uncomment אם אתה רוצה Israel time בתוך הקונטיינר
# RUN ln -snf /usr/share/zoneinfo/Asia/Jerusalem /etc/localtime && echo "Asia/Jerusalem" > /etc/timezone

# System deps (מינימלי; wheels מכסים את pandas/numpy, כך שלא צריך build-essential)
RUN apt-get update -y && apt-get install -y --no-install-recommends \
    ca-certificates curl tini \
 && rm -rf /var/lib/apt/lists/*

# App user
RUN useradd -ms /bin/bash appuser
WORKDIR /app

# Install Python deps first (better cache)
COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copy source
COPY . /app

# Healthcheck (Render קורא /health)
HEALTHCHECK --interval=30s --timeout=5s --retries=5 CMD curl -fsS "http://127.0.0.1:${PORT}/health" || exit 1

# Permissions
RUN chown -R appuser:appuser /app
USER appuser

# Expose (לא חובה ל-Render, אבל טוב לתיעוד)
EXPOSE ${PORT}

# Start (tini ל-signal handling נקי; gunicorn עם uvicorn worker)
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["bash", "-lc", "exec gunicorn -k uvicorn.workers.UvicornWorker -w 2 -b 0.0.0.0:${PORT} main:app"]










