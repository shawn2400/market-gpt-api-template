FROM python:3.11-slim

# לא מכניסים PORT כאן – Render מזריק בזמן ריצה
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MPLCONFIGDIR=/app/.mplconfig

# כלים בסיסיים + ספריות ריצה ל-Pillow/Matplotlib (Agg) + פונט דיפולטי
RUN apt-get update -y && apt-get install -y --no-install-recommends \
    ca-certificates curl tini \
    libjpeg62-turbo zlib1g libfreetype6 libpng16-16 fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*

# משתמש לא-רוט
RUN useradd -ms /bin/bash appuser
WORKDIR /app

# התקנת תלויות פייתון קודם (לטובת layer cache)
COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip && pip install -r requirements.txt

# קוד האפליקציה
COPY . /app

# תיקיות ריצה שהאפליקציה משתמשת בהן (ול-Matplotlib Agg)
RUN mkdir -p static static/reports static/snapshots "$MPLCONFIGDIR" && \
    chown -R appuser:appuser /app

USER appuser

# בריאות על "/": תואם main.py
HEALTHCHECK --interval=30s --timeout=5s --retries=5 \
  CMD curl -fsS "http://127.0.0.1:${PORT:-10000}/" || exit 1

# הפעלה עם Tini + Gunicorn/Uvicorn
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









