FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libopenblas-dev liblapack-dev libjpeg-dev libpng-dev curl \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY . .

RUN echo "תוכן /app:" && ls -la /app
RUN echo "תוכן /app/routes:" && ls -la /app/routes

RUN test -d /app/routes || (echo "❌ תיקיית routes חסרה!" && exit 1)
RUN test -f /app/routes/ai.py || (echo "❌ הקובץ /app/routes/ai.py לא קיים!" && exit 1)
RUN test -f /app/routes/__init__.py || (echo "❌ הקובץ /app/routes/__init__.py לא קיים!" && exit 1)

CMD ["gunicorn", "main:app", "-k", "uvicorn.workers.UvicornWorker", "--workers", "2", "--bind", "0.0.0.0:5000", "--timeout", "300"]








