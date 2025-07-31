FROM python:3.11-slim as base

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libopenblas-dev \
    liblapack-dev \
    libjpeg-dev \
    libpng-dev \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY . .


RUN echo "תוכן /app:" && ls -la /app
RUN echo "תוכן /app/routes:" && ls -la /app/routes || echo "תיקיית routes לא נמצאה"

CMD ["sleep", "infinity"]








