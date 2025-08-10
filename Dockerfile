# ===== Base =====
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # מניעת ריבוי ת׳רדים של BLAS במכונות קטנות
    OPENBLAS_NUM_THREADS=1 \
    OMP_NUM_THREADS=1 \
    # matplotlib cache
    MPLCONFIGDIR=/tmp/mpl \
    # לוקל בסיסי
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    TZ=Asia/Jerusalem

# תלותי מערכת Runtime + tzdata ללוגים
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates tzdata \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ===== Build deps (wheel compile) =====
FROM base AS build

# ספריות לפענוח/בנייה של wheels כבדים (numpy/pandas/matplotlib)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc build-essential gfortran \
    libssl-dev libffi-dev \
    libxml2-dev libxslt1-dev \
    libjpeg-dev zlib1g-dev \
    libfreetype6-dev libpng-dev \
    libblas-dev liblapack-dev libatlas-base-dev libopenblas-dev \
    git \
 && rm -rf /var/lib/apt/lists/*

# התקנת pip + הכנת wheels לקאש בנייה
COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade --no-cache-dir pip \
 && pip wheel --no-cache-dir --wheel-dir /app/wheels -r /app/requirements.txt

# ===== Final runtime =====
FROM base AS runtime

# ספריות runtime מינימליות לנפחי ריצה (ללא קומפיילר)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libjpeg62-turbo zlib1g \
    libfreetype6 libpng16-16 \
    libopenblas0 \
 && rm -rf /var/lib/apt/lists/*

# יוצרים יוזר לא-root
RUN useradd -m -u 10001 appuser
USER appuser

WORKDIR /app

# נעתיק גלגלים מה-build ונריץ install מהם (חוסך זמן/רשת)
COPY --from=build /app/wheels /wheels
RUN pip install --no-cache-dir /wheels/*

# קוד האפליקציה
COPY --chown=appuser:appuser . .

# תיקיות סטטיות/זמניות
RUN mkdir -p .well-known static /tmp/mpl

# Healthcheck בסיסי (Render לא תמיד משתמש, אבל טוב שיהיה)
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=5 \
  CMD curl -fsS http://127.0.0.1:${PORT:-10000}/health || exit 1

# Render מזריק PORT. נשים ברירת מחדל לריצה מקומית.
ENV PORT=10000

# Gunicorn + UvicornWorker (async). workers=1 כדי לשמור event loop יחיד ל-WS.
CMD ["bash", "-lc", "gunicorn main:app -k uvicorn.workers.UvicornWorker --workers 1 --bind 0.0.0.0:${PORT} --timeout 300"]








