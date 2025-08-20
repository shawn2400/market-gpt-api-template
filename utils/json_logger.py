# utils/json_logger.py
import logging, json, sys, uuid

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

class TraceLoggerAdapter(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        if isinstance(msg, dict):
            msg["trace_id"] = self.extra.get("trace_id", None)
            return json.dumps(msg, ensure_ascii=False), kwargs
        return msg, kwargs

def setup_json_logging():
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    return logging.getLogger("algogpt")

def get_trace_logger(trace_id: str | None = None):
    return TraceLoggerAdapter(logging.getLogger("algogpt"), {"trace_id": trace_id or str(uuid.uuid4())})


