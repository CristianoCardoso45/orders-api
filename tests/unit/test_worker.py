import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch, call

import pytest

from app.domain.entities import OutboxEvent
from app.messaging.outbox_worker import OutboxWorker, MAX_RETRIES

"""
Tests for OutboxWorker with mocked publisher and repository.

Scope: retry logic, exponential backoff, and event status transitions.

Tests _process_event directly to isolate behavior without depending on 
async_session_factory or the polling loop.
"""


@pytest.fixture
def sample_outbox_event():
    """
    Returns a sample OutboxEvent entity for testing.
    """
    return OutboxEvent(
        id=uuid.uuid4(),
        event_type="order_created",
        payload={
            "order_id": str(uuid.uuid4()),
            "external_order_id": "ORD-001",
            "requester_id": "REQ-001",
            "correlation_id": "corr-123",
        },
        status="pending",
        created_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def worker():
    """
    Returns an OutboxWorker instance with a mocked SQSPublisher.
    """
    with patch("app.messaging.outbox_worker.SQSPublisher"):
        w = OutboxWorker()
        w._publisher = AsyncMock()
        return w


async def test_should_mark_event_as_processed_on_successful_publish(
    worker, sample_outbox_event
):
    """
    Tests that an event is marked as processed after a successful publish.
    """
    mock_repo = AsyncMock()
    mock_session = AsyncMock()

    worker._publisher.publish.return_value = None

    await worker._process_event(sample_outbox_event, mock_repo, mock_session)

    mock_repo.mark_processed.assert_called_once_with(event_id=sample_outbox_event.id)
    mock_session.commit.assert_called_once()
    mock_repo.mark_failed.assert_not_called()


async def test_should_retry_with_backoff_and_succeed_on_third_attempt(
    worker, sample_outbox_event
):
    """
    Tests the retry logic with exponential backoff, succeeding on the third attempt.
    """
    mock_repo = AsyncMock()
    mock_session = AsyncMock()

    # Fails on the first two attempts, succeeds on the third
    worker._publisher.publish.side_effect = [
        Exception("error1"),
        Exception("error2"),
        None,
    ]

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        await worker._process_event(sample_outbox_event, mock_repo, mock_session)

        assert worker._publisher.publish.call_count == 3
        mock_sleep.assert_has_calls([call(1), call(5)])
        assert mock_sleep.call_count == 2

        mock_repo.mark_processed.assert_called_once_with(
            event_id=sample_outbox_event.id
        )
        mock_repo.mark_failed.assert_not_called()


async def test_should_mark_event_as_failed_after_max_retries(
    worker, sample_outbox_event
):
    """
    Tests that an event is marked as failed after reaching MAX_RETRIES.
    """
    mock_repo = AsyncMock()
    mock_session = AsyncMock()

    worker._publisher.publish.side_effect = Exception("error")

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        await worker._process_event(sample_outbox_event, mock_repo, mock_session)

        assert worker._publisher.publish.call_count == MAX_RETRIES  # 3 times
        mock_sleep.assert_has_calls([call(1), call(5)])
        assert mock_sleep.call_count == 2

        mock_repo.mark_processed.assert_not_called()
        mock_repo.mark_failed.assert_called_once_with(event_id=sample_outbox_event.id)


async def test_should_not_call_sleep_on_last_retry_attempt(worker, sample_outbox_event):
    """
    Specifically isolates the behavior of sleep to ensure it is not called on the final attempt.
    """
    mock_repo = AsyncMock()
    mock_session = AsyncMock()

    worker._publisher.publish.side_effect = Exception("error")

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        await worker._process_event(sample_outbox_event, mock_repo, mock_session)

        assert mock_sleep.call_count == 2
        mock_sleep.assert_has_calls([call(1), call(5)])
