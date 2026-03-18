import asyncio

import structlog
from opentelemetry import trace
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.domain.entities import OutboxEvent
from app.messaging.sqs_publisher import SQSPublisher
from app.observability.metrics import MESSAGES_FAILED_TOTAL, MESSAGES_PROCESSED_TOTAL
from app.repositories.database import async_session_factory
from app.repositories.outbox_repository import OutboxRepository

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)

RETRY_DELAYS = [1, 5, 30]
MAX_RETRIES = len(RETRY_DELAYS)


class OutboxWorker:
    """
    Worker that processes the Transactional Outbox.

    Runs as a separate process (does not block the API). Uses polling
    with asyncio.sleep to search for pending events periodically.

    The SELECT FOR UPDATE SKIP LOCKED in the repository ensures that multiple
    worker instances can run simultaneously without conflict.
    """

    def __init__(self) -> None:
        self._settings = get_settings()
        self._publisher = SQSPublisher()
        self._running = False

    async def start(self) -> None:
        """
        Starts the worker's polling loop.

        Runs indefinitely until stop() is called.
        Each iteration searches for a batch of pending events and attempts to publish.
        """
        self._running = True
        logger.info(
            "outbox_worker_started",
            poll_interval=self._settings.outbox_poll_interval_seconds,
            batch_size=self._settings.outbox_batch_size,
        )

        while self._running:
            try:
                await self._process_batch()
            except Exception as exc:
                logger.error(
                    "outbox_worker_batch_error",
                    error=str(exc),
                )

            await asyncio.sleep(self._settings.outbox_poll_interval_seconds)

    def stop(self) -> None:
        """Signals for the worker to stop in the next iteration."""
        self._running = False
        logger.info("outbox_worker_stopping")

    async def _process_batch(self) -> None:
        """
        Processes a batch of pending events.

        Uses a dedicated session with transaction for the SELECT FOR UPDATE SKIP LOCKED.
        Each event is processed individually with retry.
        """
        async with async_session_factory() as session:
            repo = OutboxRepository(session)
            events = await repo.fetch_pending(
                batch_size=self._settings.outbox_batch_size,
            )

            if not events:
                return

            logger.debug("outbox_batch_fetched", count=len(events))

            for event in events:
                await self._process_event(event=event, repo=repo, session=session)

    async def _process_event(
        self,
        event: OutboxEvent,
        repo: OutboxRepository,
        session: "AsyncSession",
    ) -> None:
        """
        Processes a single event with retry and exponential backoff.

        Flow:
        1. Tries to publish to SQS
        2. If success -> marks as processed
        3. If failure -> retry with backoff (1s, 5s, 30s)
        4. After exhausting retries -> marks as failed

        Args:
            event: Outbox event to process.
            repo: Outbox repository (same session/transaction).
            session: Database session for commit.
        """
        correlation_id = event.payload.get("correlation_id", "unknown")

        with tracer.start_as_current_span(
            "outbox_worker.process_event",
            attributes={
                "event_type": event.event_type,
                "event_id": str(event.id),
                "correlation_id": correlation_id,
            },
        ):
            logger.info(
                "outbox_processing_started",
                event_type=event.event_type,
                order_id=event.payload.get("order_id"),
                correlation_id=correlation_id,
            )

            for attempt in range(MAX_RETRIES):
                try:
                    await self._publisher.publish(event=event)

                    await repo.mark_processed(event_id=event.id)
                    await session.commit()

                    MESSAGES_PROCESSED_TOTAL.inc()
                    logger.info(
                        "outbox_processing_completed",
                        event_type=event.event_type,
                        order_id=event.payload.get("order_id"),
                        correlation_id=correlation_id,
                    )
                    return

                except Exception as exc:
                    delay = RETRY_DELAYS[attempt]
                    logger.warning(
                        "outbox_processing_retry",
                        event_type=event.event_type,
                        order_id=event.payload.get("order_id"),
                        error=str(exc),
                        attempt=attempt + 1,
                        max_retries=MAX_RETRIES,
                        retry_delay=delay,
                        correlation_id=correlation_id,
                    )

                    if attempt < MAX_RETRIES - 1:
                        await asyncio.sleep(delay)

            try:
                await repo.mark_failed(event_id=event.id)
                await session.commit()
            except Exception as commit_exc:
                logger.error(
                    "outbox_mark_failed_error",
                    event_id=str(event.id),
                    error=str(commit_exc),
                )

            MESSAGES_FAILED_TOTAL.inc()
            logger.error(
                "outbox_processing_failed",
                event_type=event.event_type,
                order_id=event.payload.get("order_id"),
                error="Max retries exceeded",
                attempt=MAX_RETRIES,
                correlation_id=correlation_id,
            )
