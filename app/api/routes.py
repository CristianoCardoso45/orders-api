import structlog
from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import CreateOrderRequest, OrderResponse
from app.clients.requester_client import RequesterClient
from app.config.settings import get_settings
from app.observability.middleware import get_correlation_id
from app.observability.metrics import (
    ORDERS_CREATED_TOTAL,
    ORDERS_IDEMPOTENT_TOTAL,
)
from app.repositories.database import get_session
from app.services.order_service import OrderService

logger = structlog.get_logger(__name__)

router = APIRouter()


def _get_requester_client() -> RequesterClient:
    """Factory for the requester client with configurable timeout."""
    settings = get_settings()
    return RequesterClient(
        base_url=settings.requester_service_url,
        timeout=settings.requester_service_timeout,
    )


@router.post(
    "/orders",
    response_model=OrderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create service order",
    description="Creates a new order after validating the requester. Idempotent via external_order_id.",
)
async def create_order(
    request: CreateOrderRequest,
    response: Response,
    session: AsyncSession = Depends(get_session),
    requester_client: RequesterClient = Depends(_get_requester_client),
) -> OrderResponse:
    """
    Order creation endpoint.

    Flow:
    1. Validates requester in the external service
    2. Creates order (or returns existing if idempotency)
    3. Returns 201 (created) or 200 (idempotency)
    """
    correlation_id = get_correlation_id() or "unknown"

    service = OrderService(
        session=session,
        requester_client=requester_client,
    )

    order, is_idempotent = await service.create_order(
        external_order_id=request.external_order_id,
        requester_id=request.requester_id,
        description=request.description,
        correlation_id=correlation_id,
    )

    if is_idempotent:
        response.status_code = status.HTTP_200_OK
        ORDERS_IDEMPOTENT_TOTAL.inc()
    else:
        ORDERS_CREATED_TOTAL.inc()

    return OrderResponse(
        id=order.id,
        external_order_id=order.external_order_id,
        requester_id=order.requester_id,
        description=order.description,
        status=order.status,
        created_at=order.created_at,
    )


@router.get(
    "/health",
    summary="Health check",
    description="Service health check endpoint.",
)
async def health_check() -> dict:
    """Returns service health status."""
    return {"status": "healthy"}
