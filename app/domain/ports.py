import uuid
from abc import ABC, abstractmethod

from app.domain.entities import Order, OutboxEvent


class OrderRepositoryPort(ABC):
    """Contract for order persistence."""

    @abstractmethod
    async def find_by_external_id(self, external_order_id: str) -> Order | None:
        """
        Searches for an order by external_order_id.

        Args:
            external_order_id: External order identifier (idempotency key).

        Returns:
            Found order or None.
        """
        ...

    @abstractmethod
    async def create(self, order: Order) -> Order:
        """
        Persists a new order.

        Args:
            order: Order entity to be saved.

        Returns:
            Persisted order.
        """
        ...


class OutboxRepositoryPort(ABC):
    """Contract for outbox event persistence."""

    @abstractmethod
    async def create(self, event: OutboxEvent) -> OutboxEvent:
        """
        Persists a new event in the outbox.

        Args:
            event: OutboxEvent entity to be saved.

        Returns:
            Persisted event.
        """
        ...

    @abstractmethod
    async def fetch_pending(self, batch_size: int) -> list[OutboxEvent]:
        """
        Searches for pending events with exclusive lock (SELECT FOR UPDATE SKIP LOCKED).

        Args:
            batch_size: Maximum quantity of events to search.

        Returns:
            List of pending events.
        """
        ...

    @abstractmethod
    async def mark_processed(self, event_id: uuid.UUID) -> None:
        """
        Marks an event as processed.

        Args:
            event_id: ID of the event to mark.
        """
        ...

    @abstractmethod
    async def mark_failed(self, event_id: uuid.UUID) -> None:
        """
        Marks an event as failed (after exhausting retries).

        Args:
            event_id: ID of the event to mark.
        """
        ...


class RequesterClientPort(ABC):
    """Contract for requester validation in external service."""

    @abstractmethod
    async def validate_requester(self, requester_id: str) -> bool:
        """
        Validates if the requester exists in the external service.

        Args:
            requester_id: ID of the requester to validate.

        Returns:
            True if the requester is valid.

        Raises:
            RequesterNotFoundException: If the requester does not exist (404).
            RequesterServiceUnavailableException: If the service is unavailable (5xx/timeout).
        """
        ...


class EventPublisherPort(ABC):
    """Contract for event publication in message queue."""

    @abstractmethod
    async def publish(self, event: OutboxEvent) -> None:
        """
        Publishes an event in the message queue (SQS).

        Args:
            event: Event to be published.
        """
        ...
