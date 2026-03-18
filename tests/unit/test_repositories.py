import asyncio
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities import Order, OutboxEvent
from app.repositories.order_repository import OrderRepository
from app.repositories.outbox_repository import OutboxRepository

"""
Tests for repositories with a real PostgreSQL via testcontainers.

Scope: persistence behavior, idempotency constraints,
and SELECT FOR UPDATE SKIP LOCKED.

Uses db_session from conftest — each test runs in a reverted SAVEPOINT.
"""


async def test_should_persist_order_with_all_fields(db_session: AsyncSession):
    """
    Tests that an order is correctly persisted with all its fields.
    """
    repo = OrderRepository(db_session)
    order_id = uuid.uuid4()

    order = Order(
        id=order_id,
        external_order_id="EXT-FULL-001",
        requester_id="REQ-001",
        description="A nice description",
        status="pending",
        created_at=datetime.now(timezone.utc),
    )

    await repo.create(order)

    saved_order = await repo.find_by_external_id("EXT-FULL-001")
    assert saved_order is not None
    assert saved_order.id == order_id
    assert saved_order.external_order_id == "EXT-FULL-001"
    assert saved_order.requester_id == "REQ-001"
    assert saved_order.description == "A nice description"
    assert saved_order.status == "pending"


async def test_should_raise_integrity_error_on_duplicate_external_order_id(
    db_session: AsyncSession,
):
    """
    Tests that a duplicate external_order_id raises an IntegrityError.
    """
    repo = OrderRepository(db_session)

    order1 = Order(
        id=uuid.uuid4(),
        external_order_id="DUPLICATE-001",
        requester_id="REQ-001",
        description="First",
        status="pending",
        created_at=datetime.now(timezone.utc),
    )

    order2 = Order(
        id=uuid.uuid4(),
        external_order_id="DUPLICATE-001",
        requester_id="REQ-002",
        description="Second",
        status="pending",
        created_at=datetime.now(timezone.utc),
    )

    await repo.create(order1)

    with pytest.raises(IntegrityError):
        await repo.create(order2)


async def test_should_persist_outbox_event_with_pending_status(
    db_session: AsyncSession,
):
    """
    Tests that an outbox event is persisted with the correct fields and 'pending' status.
    """
    repo = OutboxRepository(db_session)
    event_id = uuid.uuid4()

    event = OutboxEvent(
        id=event_id,
        event_type="order_created",
        payload={"foo": "bar"},
        status="pending",
        created_at=datetime.now(timezone.utc),
    )

    await repo.create(event)

    pending_events = await repo.fetch_pending(batch_size=10)
    assert len(pending_events) >= 1
    found = next((e for e in pending_events if e.id == event_id), None)

    assert found is not None
    assert found.status == "pending"
    assert found.event_type == "order_created"
    assert found.payload == {"foo": "bar"}


async def test_should_mark_event_as_processed(db_session: AsyncSession):
    """
    Tests marking an outbox event as processed.
    """
    repo = OutboxRepository(db_session)
    event_id = uuid.uuid4()

    event = OutboxEvent(
        id=event_id,
        event_type="order_created",
        payload={"foo": "bar"},
        status="pending",
        created_at=datetime.now(timezone.utc),
    )

    await repo.create(event)
    await repo.mark_processed(event_id)

    pending_events = await repo.fetch_pending(batch_size=10)
    assert not any(e.id == event_id for e in pending_events)


async def test_should_mark_event_as_failed(db_session: AsyncSession):
    """
    Tests marking an outbox event as failed.
    """
    repo = OutboxRepository(db_session)
    event_id = uuid.uuid4()

    event = OutboxEvent(
        id=event_id,
        event_type="order_created",
        payload={"foo": "bar"},
        status="pending",
        created_at=datetime.now(timezone.utc),
    )

    await repo.create(event)
    await repo.mark_failed(event_id)

    pending_events = await repo.fetch_pending(batch_size=10)
    assert not any(e.id == event_id for e in pending_events)


async def test_fetch_pending_uses_skip_locked_preventing_duplicate_processing(
    test_engine,
):
    """
    Tests lock exclusivity when fetching events.
    Verifies that multiple workers do not process the same events by using SKIP LOCKED.
    """
    # Create 4 events in the DB via a primary session that will be committed
    async with AsyncSession(test_engine) as setup_session:
        repo = OutboxRepository(setup_session)
        for i in range(4):
            event = OutboxEvent(
                id=uuid.uuid4(),
                event_type="order_created",
                payload={"index": i},
                status="pending",
                created_at=datetime.now(timezone.utc),
            )
            await repo.create(event)
        await setup_session.commit()

    async def fetch_worker():
        async with AsyncSession(test_engine) as worker_session:
            async with worker_session.begin():
                worker_repo = OutboxRepository(worker_session)
                events = await worker_repo.fetch_pending(batch_size=2)
                # Keeps the session and transaction open, holding the lock for a simulated duration
                await asyncio.sleep(0.5)
                return [e.id for e in events]

    # Executes two parallel connections
    results = await asyncio.gather(fetch_worker(), fetch_worker())

    worker1_ids, worker2_ids = results

    assert len(worker1_ids) == 2
    assert len(worker2_ids) == 2

    # Assert mutual exclusiveness
    intersection = set(worker1_ids).intersection(set(worker2_ids))
    assert len(intersection) == 0

    all_unique_ids = set(worker1_ids).union(set(worker2_ids))
    assert len(all_unique_ids) == 4

    # Cleanup state afterwards
    async with AsyncSession(test_engine) as cleanup_session:
        async with cleanup_session.begin():
            from sqlalchemy import text

            await cleanup_session.execute(text("DELETE FROM outbox_events"))
            await cleanup_session.commit()
