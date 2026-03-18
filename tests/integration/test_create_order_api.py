import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.exceptions import (
    RequesterNotFoundException,
    RequesterServiceUnavailableException,
)
from app.repositories.models import OrderModel, OutboxEventModel


async def test_should_create_order_and_return_201_with_outbox_event(
    async_client: AsyncClient,
    mock_requester_client,
    sample_order_payload,
    db_session: AsyncSession,
):
    """
    Tests the complete integration flow for creating an order.
    Verifies HTTP status 201, database persistence, and outbox event creation.
    """
    mock_requester_client.validate_requester.return_value = True

    response = await async_client.post("/orders", json=sample_order_payload)

    assert response.status_code == 201

    data = response.json()
    assert "id" in data
    assert data["external_order_id"] == "ORD-TEST-001"
    assert data["status"] == "pending"
    assert "X-Correlation-ID" in response.headers

    # Validate in database via db_session
    stmt_order = select(OrderModel).where(
        OrderModel.external_order_id == "ORD-TEST-001"
    )
    order_result = await db_session.execute(stmt_order)
    order = order_result.scalar_one_or_none()

    assert order is not None
    assert str(order.id) == data["id"]

    # Validate outbox event
    stmt_event = select(OutboxEventModel).where(
        OutboxEventModel.event_type == "order_created"
    )
    event_result = await db_session.execute(stmt_event)
    outbox_event = event_result.scalar_one_or_none()  # Since it's the only one

    assert outbox_event is not None
    assert outbox_event.status == "pending"


async def test_should_return_200_on_second_request_with_same_external_order_id(
    async_client: AsyncClient,
    mock_requester_client,
    sample_order_payload,
    db_session: AsyncSession,
):
    """
    Tests idempotency of the order creation endpoint.
    Verifies that a second request with the same external_order_id returns 200
    and does not create a duplicate order or outbox event.
    """
    # Setup req payload with specific ID
    sample_order_payload["external_order_id"] = "ORD-IDEM-001"

    response_1 = await async_client.post("/orders", json=sample_order_payload)
    assert response_1.status_code == 201

    response_2 = await async_client.post("/orders", json=sample_order_payload)
    assert response_2.status_code == 200  # Idempotency

    # Validate exactly one order via idempotence key
    stmt_order = select(OrderModel).where(
        OrderModel.external_order_id == "ORD-IDEM-001"
    )
    order_result = await db_session.execute(stmt_order)
    orders = order_result.scalars().all()
    assert len(orders) == 1

    # Exactly one outbox event total
    stmt_event = select(OutboxEventModel)
    event_result = await db_session.execute(stmt_event)
    events = event_result.scalars().all()
    assert len(events) == 1


async def test_should_return_422_when_requester_not_found(
    async_client: AsyncClient,
    mock_requester_client,
    sample_order_payload,
    db_session: AsyncSession,
):
    """
    Tests error handling when the requester is not found.
    Verifies HTTP status 422 and that no order is persisted in the database.
    """
    mock_requester_client.validate_requester.side_effect = RequesterNotFoundException(
        requester_id="REQ-999"
    )

    sample_order_payload["requester_id"] = "REQ-999"
    response = await async_client.post("/orders", json=sample_order_payload)

    assert response.status_code == 422
    assert "correlation_id" in response.json()

    # DB Should be completely empty of this
    stmt = select(OrderModel)
    count_res = await db_session.execute(stmt)
    assert len(count_res.scalars().all()) == 0


async def test_should_return_503_when_requester_service_unavailable(
    async_client: AsyncClient,
    mock_requester_client,
    sample_order_payload,
    db_session: AsyncSession,
):
    """
    Tests error handling when the requester service is unavailable.
    Verifies HTTP status 503 and that no order is persisted in the database.
    """
    mock_requester_client.validate_requester.side_effect = (
        RequesterServiceUnavailableException(requester_id="REQ-001", reason="timeout")
    )

    response = await async_client.post("/orders", json=sample_order_payload)

    assert response.status_code == 503
    assert "correlation_id" in response.json()

    stmt = select(OrderModel)
    count_res = await db_session.execute(stmt)
    assert len(count_res.scalars().all()) == 0


async def test_should_return_400_on_invalid_payload(
    async_client: AsyncClient,
):
    """
    Tests schema validation for index creation.
    Verifies HTTP status 400 when required fields are missing.
    """
    response = await async_client.post(
        "/orders",
        json={
            "external_order_id": "ONLY-EXT-ID",
            "requester_id": "REQ",
            # Missing description
        },
    )

    assert response.status_code == 400
    data = response.json()

    assert "errors" in data
    assert any(err["field"] == "body.description" for err in data["errors"])


async def test_should_return_400_on_empty_string_fields(
    async_client: AsyncClient,
    sample_order_payload,
):
    """
    Tests domain validation for empty string fields.
    Verifies HTTP status 400.
    """
    sample_order_payload["external_order_id"] = ""

    response = await async_client.post("/orders", json=sample_order_payload)

    assert response.status_code == 400


async def test_should_propagate_correlation_id_from_request_header(
    async_client: AsyncClient,
    sample_order_payload,
):
    """
    Tests that the X-Correlation-ID header is propagated back in the response.
    """
    fixed_correlation = "my-fixed-correlation-id"

    response = await async_client.post(
        "/orders",
        json=sample_order_payload,
        headers={"X-Correlation-ID": fixed_correlation},
    )

    assert response.headers["X-Correlation-ID"] == fixed_correlation


async def test_should_generate_correlation_id_when_not_provided(
    async_client: AsyncClient,
    sample_order_payload,
):
    """
    Tests that a new X-Correlation-ID is generated and returned if not provided.
    """
    response = await async_client.post("/orders", json=sample_order_payload)

    assert "X-Correlation-ID" in response.headers

    # Must be valid UUID
    header_val = response.headers["X-Correlation-ID"]
    uuid_obj = uuid.UUID(header_val)
    assert str(uuid_obj) == header_val
