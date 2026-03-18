import asyncio
import signal

import structlog

from app.config.settings import get_settings, load_secrets
from app.messaging.outbox_worker import OutboxWorker
from app.observability.logging import setup_logging
from app.observability.tracing import setup_tracing

logger = structlog.get_logger(__name__)


async def main() -> None:
    """
    Main worker function.

    Initializes observability, loads secrets, and starts the worker.
    Handles SIGTERM/SIGINT for graceful shutdown via stop flag.
    """
    settings = get_settings()

    setup_logging(log_level=settings.log_level)
    setup_tracing(service_name="order-service-worker", enabled=settings.otel_enabled)

    await load_secrets(settings=settings)

    logger.info("worker_starting")

    worker = OutboxWorker()

    loop = asyncio.get_running_loop()

    def _handle_signal() -> None:
        logger.info("worker_signal_received")
        worker.stop()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _handle_signal)
        except NotImplementedError:
            # Windows does not support add_signal_handler
            pass

    await worker.start()


if __name__ == "__main__":
    asyncio.run(main())
