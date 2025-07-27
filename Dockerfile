FROM python:3.10-slim

RUN apt-get update && apt-get install -y \
    build-essential \
    g++ \
    python3-dev \
    libatlas-base-dev \
    libffi-dev \
    libssl-dev \
    libxml2-dev \
    libxslt1-dev \
    libjpeg-dev \
    zlib1g-dev \
    libpng-dev \
    libopenblas-dev \
    curl \
    git \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# שלב יעיל: התקנת ספריות לפני העתקת כל הקוד (לביצועים)
COPY requirements.txt requirements.txt
RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# העתקת שאר הקבצים
COPY . .

EXPOSE 10000

CMD ["gunicorn", "main:app", "--bind", "0.0.0.0:10000", "--timeout", "300"]




