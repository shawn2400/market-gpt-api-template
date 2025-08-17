web: gunicorn main:app -k uvicorn.workers.UvicornWorker -w ${WORKERS:-1} -b 0.0.0.0:${PORT:-10000} --timeout 120 --graceful-timeout 30 --keep-alive 5 --log-level info

















