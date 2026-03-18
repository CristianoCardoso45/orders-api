import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class Order:
    """
    Domain entity representing a service order.

    The `external_order_id` field is the idempotency key, two orders
    should never have the same external_order_id.
    """

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    external_order_id: str = ""
    requester_id: str = ""
    description: str = ""
    status: str = "pending"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class OutboxEvent:
    """
    Transactional Outbox event.

    Saved in the same transaction as the order to ensure consistency
    between database and messaging (prevents dual-write problem).
    """

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    event_type: str = ""
    payload: dict = field(default_factory=dict)
    status: str = "pending"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
