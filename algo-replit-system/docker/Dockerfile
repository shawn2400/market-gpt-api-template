FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    build-essential \
    postgresql-client \
    redis-tools \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js for frontend
RUN curl -fsSL https://deb.nodesource.com/setup_18.x | bash - && \
    apt-get install -y nodejs

# Copy requirements
COPY requirements-algoreplit.txt .
RUN pip install --no-cache-dir -r requirements-algoreplit.txt

# Copy backend code
COPY algo-replit-system/backend /app/backend
COPY algo-replit-system/workers /app/workers

# Copy frontend code
COPY algo-replit-system/frontend /app/frontend

# Build frontend
WORKDIR /app/frontend
RUN npm install --legacy-peer-deps && \
    npm run build

WORKDIR /app

# Create workspaces directory
RUN mkdir -p /workspaces /backups

# Expose ports
EXPOSE 5000 8001 5173

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8001/health || exit 1

# Default command
CMD ["bash", "-c", "python backend/core_control_server.py & sleep infinity"]
