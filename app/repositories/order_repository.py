import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities import Order
from app.domain.ports import OrderRepositoryPort
from app.repositories.models import OrderModel

logger = structlog.get_logger(__name__)


class OrderRepository(OrderRepositoryPort):
    """
    Concrete implementation of the order persistence port.

    Receives the session via constructor (injected by the service) to
    participate in the same transaction as the outbox, essential for
    the Transactional Outbox Pattern.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_by_external_id(self, external_order_id: str) -> Order | None:
        """
        Searches for an order by external_order_id (idempotency key).

        Args:
            external_order_id: External identifier of the order.

        Returns:
            Order entity or None if not found.
        """
        stmt = select(OrderModel).where(
            OrderModel.external_order_id == external_order_id
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()

        if model is None:
            return None

        return self._to_entity(model)

    async def create(self, order: Order) -> Order:
        """
        Persists a new order in the database.

        Args:
            order: Order entity to be saved.

        Returns:
            Persisted order with fields filled by the database.
        """
        model = OrderModel(
            id=order.id,
            external_order_id=order.external_order_id,
            requester_id=order.requester_id,
            description=order.description,
            status=order.status,
            created_at=datetime.now(timezone.utc),
        )
        self._session.add(model)
        await self._session.flush()

        logger.debug(
            "order_persisted",
            order_id=str(model.id),
            external_order_id=model.external_order_id,
        )
        return self._to_entity(model)

    @staticmethod
    def _to_entity(model: OrderModel) -> Order:
        """Converts ORM model to domain entity."""
        return Order(
            id=(
                model.id
                if isinstance(model.id, uuid.UUID)
                else uuid.UUID(str(model.id))
            ),
            external_order_id=model.external_order_id,
            requester_id=model.requester_id,
            description=model.description or "",
            status=model.status,
            created_at=model.created_at,
        )
