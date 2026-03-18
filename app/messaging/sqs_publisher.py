import json

import aioboto3
import structlog
from opentelemetry import trace

from app.config.settings import get_settings
from app.domain.entities import OutboxEvent
from app.domain.ports import EventPublisherPort

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)


class SQSPublisher(EventPublisherPort):
    """
    Event publisher for Amazon SQS.

    Uses aioboto3 (async wrapper of boto3) to not block the event loop.
    The endpoint_url is configurable to point to LocalStack in dev.
    """

    def __init__(self) -> None:
        self._settings = get_settings()

    async def publish(self, event: OutboxEvent) -> None:
        """
        Publishes an event to the SQS queue.

        The payload is serialized as JSON. The MessageGroupId is not used because
        the standard queue (not FIFO) already meets the requirements, exact ordering
        is not critical for this use case.

        Args:
            event: Outbox event to be published.
        """
        with tracer.start_as_current_span(
            "sqs_publisher.publish",
            attributes={
                "event_type": event.event_type,
                "event_id": str(event.id),
            },
        ):
            session = aioboto3.Session(
                aws_access_key_id=self._settings.aws_access_key_id,
                aws_secret_access_key=self._settings.aws_secret_access_key,
                region_name=self._settings.aws_region,
            )

            async with session.client(
                "sqs",
                endpoint_url=self._settings.aws_endpoint_url,
            ) as sqs_client:
                queue_response = await sqs_client.get_queue_url(
                    QueueName=self._settings.sqs_queue_name,
                )
                queue_url = queue_response["QueueUrl"]

                message_body = json.dumps(event.payload, default=str)

                await sqs_client.send_message(
                    QueueUrl=queue_url,
                    MessageBody=message_body,
                )

                correlation_id = event.payload.get("correlation_id", "unknown")

                logger.info(
                    "outbox_event_published",
                    event_type=event.event_type,
                    order_id=event.payload.get("order_id"),
                    correlation_id=correlation_id,
                    queue=self._settings.sqs_queue_name,
                )
