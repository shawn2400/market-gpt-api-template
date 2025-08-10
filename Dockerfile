# ---- Base ----
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# אל תקבע PORT קבוע בזמן בנייה; Render/Railway מזריקות אותו בזמן ריצה.
# אם תרצה דיפולט מקומי:
ENV PORT=10000

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

# Healthcheck (בדיקת /health)
HEALTHCHECK --interval=30s --timeout=5s --retries=5 \
  CMD curl -fsS "http://127.0.0.1:${PORT}/health" || exit 1

# הרשאות
RUN chown -R appuser:appuser /app
USER appuser

# תיעוד פורט (אופציונלי)
EXPOSE ${PORT}

# הרצה: tini לניקוי סיגנלים + gunicorn עם UvicornWorker
ENTRYPOINT ["/usr/bin/tini", "--"]

# ✅ Worker יחיד כדי למנוע WS כפולים, ו-timeouts נדיבים ל-IO
CMD ["bash", "-lc", "exec gunicorn main:app \
  -k uvicorn.workers.UvicornWorker \
  --workers 1 \
  --bind 0.0.0.0:${PORT} \
  --timeout 180 \
  --graceful-timeout 30 \
  --keep-alive 75 \
  --worker-tmp-dir /dev/shm \
  --log-level info"]







