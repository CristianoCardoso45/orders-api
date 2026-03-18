import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities import Order, OutboxEvent
from app.domain.exceptions import (
    DuplicateOrderException,
    RequesterNotFoundException,
    RequesterServiceUnavailableException,
)
from app.domain.ports import RequesterClientPort
from app.services.order_service import OrderService

"""
Unit tests for OrderService.

Scope: pure business logic — order creation, idempotency,
requester validation, and error handling.

All external dependencies are mocked via patch:
- OrderRepository and OutboxRepository (created internally in the constructor)
- RequesterClientPort (injected via constructor)

The service does NOT use SQSPublisher — it only writes to the outbox.
"""


@pytest.fixture
def mock_session():
    """
    Returns an AsyncMock for AsyncSession.
    """
    return AsyncMock(spec=AsyncSession)


@pytest.fixture
def mock_requester():
    """
    Returns an AsyncMock for RequesterClientPort.
    """
    return AsyncMock(spec=RequesterClientPort)


@pytest.fixture
def sample_order():
    """
    Returns a sample Order entity for testing.
    """
    return Order(
        id=uuid.uuid4(),
        external_order_id="EXT-123",
        requester_id="REQ-001",
        description="Test Order",
        status="pending",
        created_at=datetime.now(timezone.utc),
    )


def _setup_service(mock_session, mock_requester, mock_order_repo, mock_outbox_repo):
    """
    Helper function to set up OrderService with mocked repositories.
    """
    with patch("app.services.order_service.OrderRepository") as MockOrderRepo, patch(
        "app.services.order_service.OutboxRepository"
    ) as MockOutboxRepo:
        MockOrderRepo.return_value = mock_order_repo
        MockOutboxRepo.return_value = mock_outbox_repo

        service = OrderService(session=mock_session, requester_client=mock_requester)
        return service


async def test_should_create_order_and_outbox_event_on_success(
    mock_session, mock_requester, sample_order
):
    """
    Tests successful order creation. Verifies that the order and outbox event
    are created with correct fields.
    """
    mock_order_repo = AsyncMock()
    mock_outbox_repo = AsyncMock()

    # Order does not exist
    mock_order_repo.find_by_external_id.return_value = None
    mock_order_repo.create.return_value = sample_order

    mock_requester.validate_requester.return_value = True

    service = _setup_service(
        mock_session, mock_requester, mock_order_repo, mock_outbox_repo
    )

    order, is_idempotent = await service.create_order(
        external_order_id="EXT-123",
        requester_id="REQ-001",
        description="Test description",
        correlation_id="corr-123",
    )

    assert not is_idempotent
    assert order == sample_order

    # Outbox assert
    mock_outbox_repo.create.assert_called_once()
    saved_event = mock_outbox_repo.create.call_args[1]["event"]
    created_order = mock_order_repo.create.call_args[1]["order"]

    assert isinstance(saved_event, OutboxEvent)
    assert saved_event.event_type == "order_created"
    assert saved_event.payload["order_id"] == str(created_order.id)
    assert saved_event.payload["external_order_id"] == "EXT-123"
    assert saved_event.payload["requester_id"] == "REQ-001"
    assert saved_event.payload["correlation_id"] == "corr-123"


async def test_should_return_existing_order_when_external_id_already_exists(
    mock_session, mock_requester, sample_order
):
    """
    Tests idempotency when a duplicate external_order_id is used.
    Verifies that the existing order is returned and no new entities are created.
    """
    mock_order_repo = AsyncMock()
    mock_outbox_repo = AsyncMock()

    # Order ALREADY exists
    mock_order_repo.find_by_external_id.return_value = sample_order

    service = _setup_service(
        mock_session, mock_requester, mock_order_repo, mock_outbox_repo
    )

    order, is_idempotent = await service.create_order(
        external_order_id="EXT-123",
        requester_id="REQ-001",
        description="Test description",
        correlation_id="corr-123",
    )

    assert is_idempotent
    assert order == sample_order

    mock_order_repo.create.assert_not_called()
    mock_outbox_repo.create.assert_not_called()


async def test_should_raise_requester_not_found_and_not_create_order(
    mock_session, mock_requester
):
    """
    Tests that RequesterNotFoundException is raised and no order is created.
    """
    mock_order_repo = AsyncMock()
    mock_outbox_repo = AsyncMock()

    mock_requester.validate_requester.side_effect = RequesterNotFoundException(
        requester_id="REQ-999"
    )

    service = _setup_service(
        mock_session, mock_requester, mock_order_repo, mock_outbox_repo
    )

    with pytest.raises(RequesterNotFoundException):
        await service.create_order(
            external_order_id="EXT-123",
            requester_id="REQ-999",
            description="Test description",
            correlation_id="corr-123",
        )

    mock_order_repo.create.assert_not_called()
    mock_outbox_repo.create.assert_not_called()


async def test_should_raise_service_unavailable_distinct_from_not_found(
    mock_session, mock_requester
):
    """
    Tests that RequesterServiceUnavailableException is raised appropriately.
    """
    mock_order_repo = AsyncMock()
    mock_outbox_repo = AsyncMock()

    mock_requester.validate_requester.side_effect = (
        RequesterServiceUnavailableException(requester_id="REQ-001", reason="timeout")
    )

    service = _setup_service(
        mock_session, mock_requester, mock_order_repo, mock_outbox_repo
    )

    with pytest.raises(RequesterServiceUnavailableException):
        await service.create_order(
            external_order_id="EXT-123",
            requester_id="REQ-001",
            description="Test description",
            correlation_id="corr-123",
        )

    mock_order_repo.create.assert_not_called()
    mock_outbox_repo.create.assert_not_called()


async def test_should_handle_race_condition_integrity_error_as_idempotency(
    mock_session, mock_requester, sample_order
):
    """
    Tests race condition handling where find_by_external_id returns None but
    create() raises IntegrityError. Verifies that it recovers and returns 
    the existing order.
    """
    mock_order_repo = AsyncMock()
    mock_outbox_repo = AsyncMock()

    # find_by_external_id returns None on first call, and sample_order on second (after rollback)
    mock_order_repo.find_by_external_id.side_effect = [None, sample_order]

    # create() raises IntegrityError simulating a race condition
    mock_order_repo.create.side_effect = IntegrityError(None, None, None)

    service = _setup_service(
        mock_session, mock_requester, mock_order_repo, mock_outbox_repo
    )

    order, is_idempotent = await service.create_order(
        external_order_id="EXT-123",
        requester_id="REQ-001",
        description="Test description",
        correlation_id="corr-123",
    )

    assert is_idempotent
    assert order == sample_order
    mock_session.rollback.assert_called_once()
