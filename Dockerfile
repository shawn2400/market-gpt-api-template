# ---- Base ----
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=10000

# (רשות) אזור זמן
# RUN ln -snf /usr/share/zoneinfo/Asia/Jerusalem /etc/localtime && echo "Asia/Jerusalem" > /etc/timezone

# System deps (קטן ונקי)
RUN apt-get update -y && apt-get install -y --no-install-recommends \
    ca-certificates curl tini \
 && rm -rf /var/lib/apt/lists/*

# App user
RUN useradd -ms /bin/bash appuser
WORKDIR /app

# Python deps (שומר cache של השכבה)
COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip && pip install -r requirements.txt

# קוד האפליקציה
COPY . /app

# Healthcheck (Render בודק /health)
HEALTHCHECK --interval=30s --timeout=5s --retries=5 CMD curl -fsS "http://127.0.0.1:${PORT}/health" || exit 1

# הרשאות
RUN chown -R appuser:appuser /app
USER appuser

# תיעוד פורט (Render מתעלם, אבל נחמד)
EXPOSE ${PORT}

# הרצה: tini לניקוי סיגנלים + gunicorn עם uvicorn worker
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["bash", "-lc", "exec gunicorn main:app -k uvicorn.workers.UvicornWorker -w 2 -b 0.0.0.0:${PORT} --timeout 120 --graceful-timeout 30 --keep-alive 5"]











