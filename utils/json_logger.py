# utils/json_logger.py
import logging, json, sys, uuid, os
from logging.handlers import RotatingFileHandler

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_FILE = os.getenv("LOG_FILE", "logs/algogpt.log")

class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_record = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if hasattr(record, "trace_id"):
            log_record["trace_id"] = record.trace_id
        return json.dumps(log_record, ensure_ascii=False)

class HumanFormatter(logging.Formatter):
    def format(self, record):
        return f"{record.asctime} [{record.levelname}] {record.name}: {record.getMessage()}"

class TraceLoggerAdapter(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        if isinstance(msg, dict):
            msg["trace_id"] = self.extra.get("trace_id", None)
            return json.dumps(msg, ensure_ascii=False), kwargs
        return msg, kwargs

def setup_json_logging():
    root = logging.getLogger()
    root.setLevel(LOG_LEVEL)

    # Console → JSON
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(JSONFormatter())
    root.addHandler(ch)

    # File → Human readable rotating
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        fh = RotatingFileHandler(LOG_FILE, maxBytes=5_000_000, backupCount=3, encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
        root.addHandler(fh)
    except Exception as e:
        root.error(f"Failed to init file logging: {e}")

    return logging.getLogger("algogpt")

def get_trace_logger(trace_id: str | None = None):
    return TraceLoggerAdapter(logging.getLogger("algogpt"), {"trace_id": trace_id or str(uuid.uuid4())})



