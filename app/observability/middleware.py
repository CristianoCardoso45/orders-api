import time
import uuid
from contextvars import ContextVar

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.observability.metrics import HTTP_REQUEST_DURATION

_correlation_id_ctx: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def get_correlation_id() -> str | None:
    """Gets the correlation_id from the current context."""
    return _correlation_id_ctx.get()


def set_correlation_id(correlation_id: str) -> None:
    """Sets the correlation_id in the current context."""
    _correlation_id_ctx.set(correlation_id)


logger = structlog.get_logger(__name__)


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """
    Middleware that manages the Correlation ID lifecycle.

    Flow:
    1. Reads X-Correlation-ID from the request header (propagation between services)
    2. If absent, generates a new UUID v4
    3. Sets in contextvars (accessible in any part of the async code)
    4. Sets in structlog contextvars (automatically injected into logs)
    5. Returns in the response header X-Correlation-ID
    6. Records HTTP duration metrics
    """

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        """Processes the request by injecting correlation_id and collecting metrics."""
        correlation_id = request.headers.get(
            "X-Correlation-ID",
            str(uuid.uuid4()),
        )

        set_correlation_id(correlation_id)

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(correlation_id=correlation_id)

        logger.info(
            "request_received",
            method=request.method,
            path=request.url.path,
            correlation_id=correlation_id,
        )

        start_time = time.perf_counter()

        response = await call_next(request)

        duration = time.perf_counter() - start_time

        HTTP_REQUEST_DURATION.labels(
            method=request.method,
            endpoint=request.url.path,
            status_code=str(response.status_code),
        ).observe(duration)

        response.headers["X-Correlation-ID"] = correlation_id

        return response
