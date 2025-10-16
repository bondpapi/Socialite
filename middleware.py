from __future__ import annotations

import time
from typing import Callable

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from social_agent_ai.services.metrics import log_http, init_metrics_tables


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable):
        start = time.perf_counter()
        try:
            response = await call_next(request)
            return response
        finally:
            dur_ms = int((time.perf_counter() - start) * 1000)
            try:
                route = request.scope.get("path") or request.url.path
                method = request.method
                status = getattr(request.state, "status_code", None) or getattr(response, "status_code", 500)
                log_http(route=route, method=method, status=status, duration_ms=dur_ms)
            except Exception:
                pass


init_metrics_tables()
