# ===== Base =====
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    OPENBLAS_NUM_THREADS=1 \
    OMP_NUM_THREADS=1 \
    MPLCONFIGDIR=/tmp/mpl \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    TZ=Asia/Jerusalem

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates tzdata \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ===== Build (wheels) =====
FROM base AS build

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc build-essential gfortran \
    libssl-dev libffi-dev \
    libxml2-dev libxslt1-dev \
    libjpeg-dev zlib1g-dev \
    libfreetype6-dev libpng-dev \
    libblas-dev liblapack-dev libatlas-base-dev libopenblas-dev \
    git \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt

RUN pip install --upgrade --no-cache-dir pip \
 && pip wheel --no-cache-dir --wheel-dir /app/wheels -r /app/requirements.txt

# ===== Runtime =====
FROM base AS runtime

# ספריות runtime מינימליות
RUN apt-get update && apt-get install -y --no-install-recommends \
    libjpeg62-turbo zlib1g \
    libfreetype6 libpng16-16 \
    libopenblas0 \
 && rm -rf /var/lib/apt/lists/*

# צור משתמש ותן לו בעלות על /app + צור תיקיות בסיס כ-root
RUN useradd -m -u 10001 appuser \
 && mkdir -p /app /app/.well-known /app/static /tmp/mpl \
 && chown -R appuser:appuser /app /tmp/mpl

WORKDIR /app

# התקנת wheels
COPY --from=build /app/wheels /wheels
RUN pip install --no-cache-dir /wheels/*

# קוד האפליקציה בבעלות appuser
COPY --chown=appuser:appuser . .

# הוספת bin של user ל-PATH כדי להעלים אזהרות (uvicorn/gunicorn וכו')
ENV PATH="/home/appuser/.local/bin:${PATH}"

USER appuser

# Healthcheck
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=5 \
  CMD curl -fsS http://127.0.0.1:${PORT:-10000}/health || exit 1

# Render/Railway מזריקים PORT; ברירת מחדל ל-local
ENV PORT=10000

# שרת
CMD ["bash", "-lc", "gunicorn main:app -k uvicorn.workers.UvicornWorker --workers 1 --bind 0.0.0.0:${PORT} --timeout 300"]









