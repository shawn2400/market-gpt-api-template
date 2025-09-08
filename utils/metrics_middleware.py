# utils/metrics_middleware.py
import time
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from utils import metrics_exporter

class MetricsMiddleware(BaseHTTPMiddleware):
    """
    Middleware ל-FastAPI שמודד זמני תגובה, סטטוס, נתיב ושולח ל-Prometheus.
    """

    async def dispatch(self, request: Request, call_next):
        start_time = time.perf_counter()

        try:
            response: Response = await call_next(request)
            status_code = response.status_code
        except Exception:
            # שגיאה פנימית = 500
            status_code = 500
            raise
        finally:
            latency = time.perf_counter() - start_time
            path = request.url.path
            method = request.method

            # רושם למטריקות
            metrics_exporter.record_api_request(
                path=path,
                method=method,
                status=status_code,
                latency=latency
            )

        return response
