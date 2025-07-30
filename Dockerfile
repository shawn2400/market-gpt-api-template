# Base image with Python 3.11
FROM python:3.11-slim

# Environment settings
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

# Metadata labels
LABEL maintainer="AlgoGPT Team <dev@algogpt.ai>" \
      version="1.3.1" \
      description="AlgoGPT Docker Image for FastAPI Trading Bot"

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libopenblas-dev \
    liblapack-dev \
    libjpeg-dev \
    libpng-dev \
    curl \
 && apt-get clean && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Install Python-level dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
 && pip install --no-cache-dir cython numpy==1.26.4 \
 && pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose application port
EXPOSE 5000

# Healthcheck configuration
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl --fail http://localhost:5000/ || exit 1

# Start Gunicorn with Uvicorn worker, increased timeouts and graceful shutdown
CMD ["gunicorn", "main:app", \
      "-k", "uvicorn.workers.UvicornWorker", \
      "--bind", "0.0.0.0:5000", \
      "--workers", "2", \
      "--timeout", "180", \
      "--graceful-timeout", "30"]


















