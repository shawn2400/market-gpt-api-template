FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc build-essential libpq-dev libssl-dev libffi-dev \
    libxml2-dev libxslt1-dev libjpeg-dev zlib1g-dev \
    libblas-dev liblapack-dev libatlas-base-dev gfortran \
    libfreetype6-dev libpng-dev libopenblas-dev \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p .well-known static

# חשוב: מאזין ל-$PORT של Railway
CMD ["bash", "-lc", "gunicorn main:app -k uvicorn.workers.UvicornWorker --workers 2 --bind 0.0.0.0:${PORT} --timeout 300"]




