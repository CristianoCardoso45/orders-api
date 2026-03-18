import uuid
from datetime import datetime, timezone

import structlog
from opentelemetry import trace
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities import Order, OutboxEvent
from app.domain.exceptions import DuplicateOrderException
from app.domain.ports import (
    OrderRepositoryPort,
    OutboxRepositoryPort,
    RequesterClientPort,
)
from app.repositories.order_repository import OrderRepository
from app.repositories.outbox_repository import OutboxRepository

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)


class OrderService:
    """
    Orchestration service for order creation.

    Coordinates requester validation, idempotency check,
    persistence (order + outbox) in a single transaction, and handling
    of race conditions via IntegrityError.
    """

    def __init__(
        self,
        session: AsyncSession,
        requester_client: RequesterClientPort,
    ) -> None:
        self._session = session
        self._requester_client = requester_client
        self._order_repo: OrderRepositoryPort = OrderRepository(session)
        self._outbox_repo: OutboxRepositoryPort = OutboxRepository(session)

    async def create_order(
        self,
        external_order_id: str,
        requester_id: str,
        description: str,
        correlation_id: str,
    ) -> tuple[Order, bool]:
        """
        Creates a new service order.

        Flow:
        1. Validate requester in the external service
        2. Check idempotency (search by external_order_id)
        3. If existing order -> return with flag is_idempotent=True
        4. Create order + outbox event in the same transaction
        5. Commit
        6. In case of IntegrityError (race condition) -> search and return

        Args:
            external_order_id: External identifier of the order (idempotency key).
            requester_id: ID of the requester to validate.
            description: Description of the order.
            correlation_id: Correlation ID for traceability.

        Returns:
            Tuple (Order, is_idempotent). is_idempotent=True indicates an idempotency hit.

        Raises:
            RequesterNotFoundException: Invalid requester.
            RequesterServiceUnavailableException: Requester service unavailable.
        """
        with tracer.start_as_current_span(
            "order_service.create_order",
            attributes={
                "external_order_id": external_order_id,
                "requester_id": requester_id,
                "correlation_id": correlation_id,
            },
        ):
            await self._requester_client.validate_requester(requester_id=requester_id)

            existing_order = await self._order_repo.find_by_external_id(
                external_order_id=external_order_id,
            )

            if existing_order is not None:
                logger.info(
                    "idempotency_hit",
                    external_order_id=external_order_id,
                    existing_order_id=str(existing_order.id),
                    correlation_id=correlation_id,
                )
                return existing_order, True

            try:
                order, _ = await self._create_order_with_outbox(
                    external_order_id=external_order_id,
                    requester_id=requester_id,
                    description=description,
                    correlation_id=correlation_id,
                )
                return order, False

            except IntegrityError:
                await self._session.rollback()

                existing = await self._order_repo.find_by_external_id(
                    external_order_id=external_order_id,
                )
                if existing is not None:
                    logger.info(
                        "idempotency_hit",
                        external_order_id=external_order_id,
                        existing_order_id=str(existing.id),
                        correlation_id=correlation_id,
                        source="race_condition",
                    )
                    return existing, True

                raise DuplicateOrderException(external_order_id=external_order_id)

    async def _create_order_with_outbox(
        self,
        external_order_id: str,
        requester_id: str,
        description: str,
        correlation_id: str,
    ) -> tuple[Order, OutboxEvent]:
        """
        Creates order and outbox event in a single transaction.

        Transactional Outbox Pattern: the order and the event are saved
        atomically. The worker processes the outbox later and publishes to SQS.
        This avoids the dual-write problem (publishing an event without committing the order,
        or vice versa).

        Args:
            external_order_id: External identifier of the order.
            requester_id: ID of the requester.
            description: Description of the order.
            correlation_id: Correlation ID.

        Returns:
            Tuple (Order, OutboxEvent) created in the transaction.
        """
        order_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        order = Order(
            id=order_id,
            external_order_id=external_order_id,
            requester_id=requester_id,
            description=description,
            status="pending",
            created_at=now,
        )

        outbox_event = OutboxEvent(
            id=uuid.uuid4(),
            event_type="order_created",
            payload={
                "event_type": "order_created",
                "order_id": str(order_id),
                "external_order_id": external_order_id,
                "requester_id": requester_id,
                "correlation_id": correlation_id,
                "created_at": now.isoformat(),
            },
            status="pending",
            created_at=now,
        )

        created_order = await self._order_repo.create(order=order)
        await self._outbox_repo.create(event=outbox_event)

        await self._session.commit()

        logger.info(
            "order_created",
            order_id=str(created_order.id),
            external_order_id=external_order_id,
            correlation_id=correlation_id,
        )

        return created_order, outbox_event
