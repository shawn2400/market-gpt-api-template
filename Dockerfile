FROM python:3.11-slim as base

# התקנות רק ברמה הבסיסית
RUN apt-get update && apt-get install -y --no-install-recommends \
    libopenblas-dev liblapack-dev libjpeg-dev libpng-dev curl \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
WORKDIR /app

RUN pip install --no-cache-dir -r requirements.txt
COPY . .

CMD ["gunicorn", "main:app", "-k", "uvicorn.workers.UvicornWorker", "--workers", "2", "--bind", "0.0.0.0:5000", "--timeout", "300"]




















