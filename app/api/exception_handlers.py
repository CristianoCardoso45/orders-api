import structlog
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.domain.exceptions import (
    DuplicateOrderException,
    RequesterNotFoundException,
    RequesterServiceUnavailableException,
)
from app.observability.middleware import get_correlation_id
from app.observability.metrics import ORDERS_FAILED_TOTAL

logger = structlog.get_logger(__name__)


def _get_current_correlation_id() -> str:
    """Gets the correlation_id from the current context."""
    return get_correlation_id() or "unknown"


async def requester_not_found_handler(
    request: Request,
    exc: RequesterNotFoundException,
) -> JSONResponse:
    """
    RequesterNotFoundException -> HTTP 422.

    422 (Unprocessable Entity) because the payload is syntactically valid,
    but semantically invalid, the requester_id does not correspond to an
    existing requester.
    """
    correlation_id = _get_current_correlation_id()
    logger.warning(
        "requester_not_found",
        requester_id=exc.requester_id,
        correlation_id=correlation_id,
    )
    ORDERS_FAILED_TOTAL.labels(error_type="requester_not_found").inc()
    return JSONResponse(
        status_code=422,
        content={
            "detail": f"Solicitante não encontrado: {exc.requester_id}",
            "correlation_id": correlation_id,
        },
    )


async def requester_unavailable_handler(
    request: Request,
    exc: RequesterServiceUnavailableException,
) -> JSONResponse:
    """
    RequesterServiceUnavailableException -> HTTP 503.

    503 (Service Unavailable) indicates to the client that it is a temporary error
    and that they should try again after an interval.
    """
    correlation_id = _get_current_correlation_id()
    logger.error(
        "requester_unavailable",
        requester_id=exc.requester_id,
        error=exc.reason,
        correlation_id=correlation_id,
    )
    ORDERS_FAILED_TOTAL.labels(error_type="requester_unavailable").inc()
    return JSONResponse(
        status_code=503,
        content={
            "detail": "Serviço de solicitantes temporariamente indisponível. Tente novamente.",
            "correlation_id": correlation_id,
        },
    )


async def duplicate_order_handler(
    request: Request,
    exc: DuplicateOrderException,
) -> JSONResponse:
    """
    DuplicateOrderException (race condition) -> HTTP 200.

    Treated as idempotency: returns 200 instead of 409 so that
    automatic client retries work transparently.

    Note: the body here is a fallback, normally the service already
    retrieves the existing order and returns normally.
    """
    correlation_id = _get_current_correlation_id()
    logger.info(
        "idempotency_hit",
        external_order_id=exc.external_order_id,
        correlation_id=correlation_id,
        source="exception_handler",
    )
    return JSONResponse(
        status_code=200,
        content={
            "detail": "Ordem já existente (idempotência).",
            "correlation_id": correlation_id,
        },
    )


async def validation_error_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    """
    Pydantic ValidationError -> HTTP 400.

    Returns details of the invalid fields without exposing internal information.
    """
    correlation_id = _get_current_correlation_id()
    errors = []
    for err in exc.errors():
        errors.append(
            {
                "field": ".".join(str(loc) for loc in err["loc"]),
                "message": err["msg"],
            }
        )

    logger.warning(
        "request_validation_failed",
        errors=errors,
        correlation_id=correlation_id,
    )
    ORDERS_FAILED_TOTAL.labels(error_type="validation_error").inc()
    return JSONResponse(
        status_code=400,
        content={
            "detail": "Dados da requisição inválidos.",
            "errors": errors,
            "correlation_id": correlation_id,
        },
    )


async def generic_error_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    """
    Unexpected errors -> HTTP 500.

    Never exposes stack traces or internal details. Includes correlation_id
    so that the support team can locate the error in the logs.
    """
    correlation_id = _get_current_correlation_id()
    logger.exception(
        "unhandled_error",
        error=str(exc),
        correlation_id=correlation_id,
    )
    ORDERS_FAILED_TOTAL.labels(error_type="internal_error").inc()
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Erro interno do servidor.",
            "correlation_id": correlation_id,
        },
    )
