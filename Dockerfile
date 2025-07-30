# Dockerfile — גרסה 1.3.0 מעודכנת

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

LABEL maintainer="AlgoGPT Team <dev@algogpt.ai>" \
      version="1.3.0" \
      description="AlgoGPT Docker Image for FastAPI Trading Bot"

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libopenblas-dev liblapack-dev libjpeg-dev libpng-dev curl \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir cython numpy==1.26.4 && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl --fail http://localhost:5000/ || exit 1

CMD ["gunicorn", "main:app", "-k", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:5000", "--timeout", "180"]

















