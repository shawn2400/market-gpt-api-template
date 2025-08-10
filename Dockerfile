FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # מניעת ריבוי ת׳רדים של BLAS במכונות קטנות
    OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
    # תיקיית קאש ל-matplotlib (שימושית אם תרצה להריץ כ־non-root בעתיד)
    MPLCONFIGDIR=/tmp/mpl

# ספריות מערכת שנדרשות ל-numpy/pandas/matplotlib וכו'
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc build-essential libpq-dev libssl-dev libffi-dev \
    libxml2-dev libxslt1-dev libjpeg-dev zlib1g-dev \
    libblas-dev liblapack-dev libatlas-base-dev gfortran \
    libfreetype6-dev libpng-dev libopenblas-dev \
    curl ca-certificates \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# תלותי פייתון
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# קוד האפליקציה
COPY . .

# תיקיות סטטיות (לא חובה)
RUN mkdir -p .well-known static /tmp/mpl

# (אופציונלי) Healthcheck בסיסי – Render לא חייב, אבל טוב שיהיה
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=5 \
  CMD curl -fsS http://127.0.0.1:${PORT:-10000}/health || exit 1

# Gunicorn יקשיב ל-$PORT שמוזרק ע"י Render
CMD ["bash", "-lc", "gunicorn main:app -k uvicorn.workers.UvicornWorker --workers 1 --bind 0.0.0.0:${PORT} --timeout 300"]






