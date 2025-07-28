FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc libffi-dev && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
COPY main.py .
COPY trade_executor.py .
COPY scanner_utils.py .
COPY backtest_utils.py .
COPY utils/ ./utils/

RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 8080
EXPOSE 5000

CMD ["python", "main.py"]










