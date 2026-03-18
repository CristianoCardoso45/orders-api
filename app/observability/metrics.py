from prometheus_client import Counter, Histogram, generate_latest
from fastapi import APIRouter
from fastapi.responses import Response


ORDERS_CREATED_TOTAL = Counter(
    "orders_created_total",
    "Total successfully created orders",
)

ORDERS_IDEMPOTENT_TOTAL = Counter(
    "orders_idempotent_total",
    "Total idempotency hits (existing order)",
)

ORDERS_FAILED_TOTAL = Counter(
    "orders_failed_total",
    "Total failures in order creation",
    ["error_type"],
)


MESSAGES_PROCESSED_TOTAL = Counter(
    "messages_processed_total",
    "Total outbox messages successfully published to SQS",
)

MESSAGES_FAILED_TOTAL = Counter(
    "messages_failed_total",
    "Total outbox messages that failed after all retries",
)


HTTP_REQUEST_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "endpoint", "status_code"],
)


metrics_router = APIRouter()


@metrics_router.get(
    "/metrics",
    summary="Prometheus metrics",
    description="Scraping endpoint for Prometheus.",
    include_in_schema=False,
)
async def metrics_endpoint() -> Response:
    """Returns metrics in Prometheus text exposition format."""
    return Response(
        content=generate_latest(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
