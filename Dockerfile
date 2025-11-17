# Production Dockerfile for AlgoGPT
FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DEBIAN_FRONTEND=noninteractive \
    TZ=Asia/Jerusalem \
    PORT=10000

# Install system dependencies including monitoring tools
RUN apt-get update -y \
 && apt-get install -y --no-install-recommends \
    tini \
    ca-certificates \
    tzdata \
    curl \
    procps \
    net-tools \
 && ln -fs /usr/share/zoneinfo/$TZ /etc/localtime \
 && dpkg-reconfigure -f noninteractive tzdata \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN python -m pip install --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

COPY . .

# Copy startup script and make executable
COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh

EXPOSE 10000
HEALTHCHECK --interval=30s --timeout=8s --retries=5 \
  CMD curl -fsS http://127.0.0.1:${PORT}/readyz || exit 1

ENTRYPOINT ["/usr/bin/tini","--"]
CMD ["/app/start.sh"]
