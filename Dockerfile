FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
    # ⚠️ אל תקבע כאן PORT; Render מזריק PORT בזמן ריצה.

RUN apt-get update -y && apt-get install -y --no-install-recommends \
    ca-certificates curl tini \
 && rm -rf /var/lib/apt/lists/*

# משתמש לא-רוט
RUN useradd -ms /bin/bash appuser
WORKDIR /app

# התקנת תלויות
COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip && pip install -r requirements.txt

# קוד האפליקציה
COPY . /app

# ✅ בריאות על "/": זה הנתיב הזמין ב-main.py
HEALTHCHECK --interval=30s --timeout=5s --retries=5 \
  CMD curl -fsS "http://127.0.0.1:${PORT:-10000}/" || exit 1

RUN chown -R appuser:appuser /app
USER appuser

# (אין צורך ב-EXPOSE ב-Render)
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








