from __future__ import annotations
import time
import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# נסיון לייבא את מודול המטריקות; אם חסר – ניצור shim שלא מפיל את האפליקציה
try:
    from . import metrics_exporter  # type: ignore
except Exception:
    class _NoopMetricsExporter:
        def record_api_request(self, *args, **kwargs):
            pass
    metrics_exporter = _NoopMetricsExporter()  # type: ignore

log = logging.getLogger("algogpt.metrics_mw")

class MetricsMiddleware(BaseHTTPMiddleware):
    """
    מודד לטנסי, סופר בקשות, מתעד 5xx.
    חשוב: עטוף try/except סביב המטריקות כדי לא להפיל את האפליקציה במקרה של חוסר תאימות.
    """

    async def dispatch(self, request: Request, call_next):
        t0 = time.perf_counter()
        path = request.url.path
        method = request.method

        try:
            response: Response = await call_next(request)
            status = getattr(response, "status_code", 500)
            latency = time.perf_counter() - t0
            # ניסוי לקבל content-length; אם אין — נוותר בשקט
            bytes_out = 0
            try:
                cl = response.headers.get("content-length")
                if cl:
                    bytes_out = int(cl)
            except Exception:
                bytes_out = 0

            try:
                metrics_exporter.record_api_request(
                    path=path,
                    method=method,
                    status_code=status,
                    latency=latency,           # חדש
                    bytes_out=bytes_out,       # אופציונלי
                )
            except TypeError:
                # תאימות לממשק הישן
                try:
                    metrics_exporter.record_api_request(path, method, status, latency)
                except Exception as e:
                    log.debug("metrics(record_api_request legacy) failed: %r", e)
            except Exception as e:
                log.debug("metrics(record_api_request) failed: %r", e)

            return response

        except Exception:
            # במקרה של חריגה — נרשום 5xx עם זמן שחלף ונעביר הלאה
            latency = time.perf_counter() - t0
            try:
                metrics_exporter.record_api_request(
                    path=path,
                    method=method,
                    status_code=500,
                    latency=latency,
                )
            except Exception as e:
                log.debug("metrics(record_api_request on exception) failed: %r", e)
            raise


