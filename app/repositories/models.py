import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base for all SQLAlchemy models."""

    pass


class OrderModel(Base):
    """
    ORM model for the `orders` table.

    The UNIQUE constraint on `external_order_id` is the last line of defense
    for idempotency: even if the application check fails in a race condition,
    the database rejects duplicates with an IntegrityError.
    """

    __tablename__ = "orders"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    external_order_id: Mapped[str] = mapped_column(
        unique=True,
        nullable=False,
        index=True,
        comment="Idempotency key, ensures uniqueness at the database level",
    )
    requester_id: Mapped[str] = mapped_column(nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        default=lambda: datetime.now(timezone.utc),
    )


class OutboxEventModel(Base):
    """
    ORM model for the `outbox_events` table (Transactional Outbox Pattern).

    The payload is stored as JSONB, a native PostgreSQL type that allows
    indexing and queries inside the JSON, useful for debugging and auditing.

    The `status` field controls the lifecycle: pending -> processed | failed
    """

    __tablename__ = "outbox_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    event_type: Mapped[str] = mapped_column(nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(
        nullable=False,
        default="pending",
        index=True,
        comment="Lifecycle: pending -> processed | failed",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        default=lambda: datetime.now(timezone.utc),
    )
