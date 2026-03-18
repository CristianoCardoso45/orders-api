from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

import structlog
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from app.api.exception_handlers import (
    duplicate_order_handler,
    generic_error_handler,
    requester_not_found_handler,
    requester_unavailable_handler,
    validation_error_handler,
)
from app.api.routes import router
from app.config.settings import get_settings
from app.domain.exceptions import (
    DuplicateOrderException,
    RequesterNotFoundException,
    RequesterServiceUnavailableException,
)
from app.observability.logging import setup_logging
from app.observability.metrics import metrics_router
from app.observability.middleware import CorrelationIdMiddleware
from app.observability.tracing import setup_tracing
from app.repositories.database import dispose_engine

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    FastAPI lifespan, manages startup and shutdown.

    Startup:
    1. Configures structured logs
    2. Configures tracing (OpenTelemetry)
    3. Loads secrets (Secrets Manager or fallback)

    Shutdown:
    1. Closes database connection pool
    """
    settings = get_settings()

    setup_logging(log_level=settings.log_level)
    setup_tracing(enabled=settings.otel_enabled)

    from app.config.settings import load_secrets

    await load_secrets(settings=settings)

    logger.info("application_started", log_level=settings.log_level)

    yield

    await dispose_engine()
    logger.info("application_stopped")


app = FastAPI(
    title="Order Service",
    version="1.0.0",
    description="Microsserviço de registro de ordens de serviço",
    lifespan=lifespan,
)

app.add_middleware(CorrelationIdMiddleware)


app.include_router(router)
app.include_router(metrics_router)

app.add_exception_handler(RequesterNotFoundException, requester_not_found_handler)
app.add_exception_handler(
    RequesterServiceUnavailableException, requester_unavailable_handler
)
app.add_exception_handler(DuplicateOrderException, duplicate_order_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)
app.add_exception_handler(Exception, generic_error_handler)
