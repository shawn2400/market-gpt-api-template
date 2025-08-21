# gunicorn_conf.py
import multiprocessing, os, json, sys, logging

#
# Workers & Performance
#
workers = int(os.getenv("WORKERS", multiprocessing.cpu_count() * 2 + 1))
worker_class = "uvicorn.workers.UvicornWorker"
bind = f"0.0.0.0:{os.getenv('PORT', '8000')}"

timeout = 120
graceful_timeout = 30
keepalive = 5

max_requests = 2000
max_requests_jitter = 200
worker_tmp_dir = "/dev/shm"
worker_connections = 1000  # מתאים ל-WS כבדים
preload_app = True         # חוסך זמן וזיכרון ב-startup

#
# JSON Structured Logging
#
class JSONGunicornHandler(logging.StreamHandler):
    def emit(self, record):
        try:
            log_record = {
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            }
            if hasattr(record, "trace_id"):
                log_record["trace_id"] = record.trace_id
            self.stream.write(json.dumps(log_record, ensure_ascii=False) + "\n")
            self.flush()
        except Exception:
            self.handleError(record)


def post_worker_init(worker):
    """
    Hook: configure JSON logging inside Gunicorn workers
    """
    root = logging.getLogger()
    for h in root.handlers[:]:
        root.removeHandler(h)
    handler = JSONGunicornHandler(sys.stdout)
    root.addHandler(handler)
    root.setLevel(logging.INFO)


#
# Gunicorn log settings
#
loglevel = "info"
accesslog = "-"
errorlog = "-"

# Custom access log format → JSON
access_log_format = (
    '{"event":"access","client":"%(h)s","request":"%(r)s","status":"%(s)s",'
    '"size":"%(b)s","referer":"%(f)s","agent":"%(a)s","duration":"%(L)s"}'
)







