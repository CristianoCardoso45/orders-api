import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities import OutboxEvent
from app.domain.ports import OutboxRepositoryPort
from app.repositories.models import OutboxEventModel

logger = structlog.get_logger(__name__)


class OutboxRepository(OutboxRepositoryPort):
    """
    Concrete implementation of the outbox persistence port.

    Participates in the same transaction as the OrderRepository to ensure
    atomicity between order creation and event creation (Transactional Outbox).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, event: OutboxEvent) -> OutboxEvent:
        """
        Persists a new event in the outbox.

        Args:
            event: OutboxEvent entity to be saved.

        Returns:
            Persisted event.
        """
        model = OutboxEventModel(
            id=event.id,
            event_type=event.event_type,
            payload=event.payload,
            status=event.status,
            created_at=datetime.now(timezone.utc),
        )
        self._session.add(model)
        await self._session.flush()

        logger.debug(
            "outbox_event_persisted",
            event_id=str(model.id),
            event_type=model.event_type,
        )
        return self._to_entity(model)

    async def fetch_pending(self, batch_size: int) -> list[OutboxEvent]:
        """
        Searches for pending events with exclusive lock.

        Uses SELECT FOR UPDATE SKIP LOCKED to allow multiple
        worker instances to process events in parallel without conflict:
        each instance takes an exclusive batch, events already locked by another
        instance are simply ignored.

        Args:
            batch_size: Maximum quantity of events to search.

        Returns:
            List of pending events (exclusively locked by this session).
        """
        stmt = (
            select(OutboxEventModel)
            .where(OutboxEventModel.status == "pending")
            .order_by(OutboxEventModel.created_at.asc())
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
        result = await self._session.execute(stmt)
        models = result.scalars().all()
        return [self._to_entity(m) for m in models]

    async def mark_processed(self, event_id: uuid.UUID) -> None:
        """
        Marks event as processed after successful publication to SQS.

        Args:
            event_id: ID of the event to mark.
        """
        stmt = (
            update(OutboxEventModel)
            .where(OutboxEventModel.id == event_id)
            .values(status="processed")
        )
        await self._session.execute(stmt)

    async def mark_failed(self, event_id: uuid.UUID) -> None:
        """
        Marks event as failed after exhausting retries.

        Events marked as 'failed' will not be reprocessed automatically.
        They require manual intervention or a reconciliation process.

        Args:
            event_id: ID of the event to mark.
        """
        stmt = (
            update(OutboxEventModel)
            .where(OutboxEventModel.id == event_id)
            .values(status="failed")
        )
        await self._session.execute(stmt)

    @staticmethod
    def _to_entity(model: OutboxEventModel) -> OutboxEvent:
        """Converts ORM model to domain entity."""
        return OutboxEvent(
            id=(
                model.id
                if isinstance(model.id, uuid.UUID)
                else uuid.UUID(str(model.id))
            ),
            event_type=model.event_type,
            payload=model.payload,
            status=model.status,
            created_at=model.created_at,
        )
