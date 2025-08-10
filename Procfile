gunicorn main:app \
  -k uvicorn.workers.UvicornWorker \
  -w 1 \
  -t 120 \
  --graceful-timeout 30 \
  --keep-alive 5 \
  -b 0.0.0.0:$PORT
















