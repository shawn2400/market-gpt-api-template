gunicorn -k uvicorn.workers.UvicornWorker main:app \
  --bind 0.0.0.0:${PORT:-10000} \
  --workers 2 \
  --timeout 120 \
  --graceful-timeout 30 \
  --log-level info
















