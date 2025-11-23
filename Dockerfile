# Production Dockerfile for AlgoGPT v10.4.0
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV TZ=Asia/Jerusalem
ENV PORT=8008

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y \
    python3.11 python3.11-dev python3-pip \
    git curl wget unzip nano jq build-essential \
    ca-certificates apt-transport-https tini \
    && rm -rf /var/lib/apt/lists/*

# Copy Python dependencies
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Make scripts executable
RUN chmod +x /app/start.sh /app/install.sh 2>/dev/null || true

# Create necessary directories
RUN mkdir -p workspace backups logs data

EXPOSE 8008 8080 8443 11434

HEALTHCHECK --interval=30s --timeout=8s --retries=5 \
    CMD curl -fsS http://127.0.0.1:${PORT}/readyz || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["/app/start.sh"]
