import httpx
import structlog
from opentelemetry import trace

from app.domain.exceptions import (
    RequesterNotFoundException,
    RequesterServiceUnavailableException,
)
from app.domain.ports import RequesterClientPort

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)


class RequesterClient(RequesterClientPort):
    """
    HTTP client for requester validation.

    Uses httpx.AsyncClient for its clean API, native timeout support,
    and good integration with Python typing. The configurable timeout (default 3s)
    prevents external service slowness from causing cascading failures.
    """

    def __init__(self, base_url: str, timeout: float = 3.0) -> None:
        self._base_url = base_url
        self._timeout = timeout

    async def validate_requester(self, requester_id: str) -> bool:
        """
        Validates if the requester exists in the external service.

        Error mapping (boundary anti-corruption layer):
        - 200-299 -> valid requester
        - 404     -> RequesterNotFoundException (business error)
        - 5xx     -> RequesterServiceUnavailableException (infrastructure error)
        - Timeout -> RequesterServiceUnavailableException (infrastructure error)

        Args:
            requester_id: ID of the requester to validate.

        Returns:
            True if the requester is valid.

        Raises:
            RequesterNotFoundException: Requester not found.
            RequesterServiceUnavailableException: Service unavailable.
        """
        with tracer.start_as_current_span(
            "requester_client.validate",
            attributes={"requester_id": requester_id},
        ):
            try:
                async with httpx.AsyncClient(
                    base_url=self._base_url,
                    timeout=self._timeout,
                ) as client:
                    response = await client.get(f"/requesters/{requester_id}")

                if response.status_code == 404:
                    logger.warning(
                        "requester_not_found",
                        requester_id=requester_id,
                    )
                    raise RequesterNotFoundException(requester_id=requester_id)

                if response.status_code >= 500:
                    logger.error(
                        "requester_unavailable",
                        requester_id=requester_id,
                        error=f"HTTP {response.status_code}",
                    )
                    raise RequesterServiceUnavailableException(
                        requester_id=requester_id,
                        reason=f"HTTP {response.status_code}",
                    )

                response.raise_for_status()
                return True

            except (RequesterNotFoundException, RequesterServiceUnavailableException):
                raise

            except httpx.TimeoutException:
                logger.error(
                    "requester_unavailable",
                    requester_id=requester_id,
                    error="timeout",
                )
                raise RequesterServiceUnavailableException(
                    requester_id=requester_id,
                    reason=f"Timeout after {self._timeout}s",
                )

            except httpx.HTTPError as exc:
                logger.error(
                    "requester_unavailable",
                    requester_id=requester_id,
                    error=str(exc),
                )
                raise RequesterServiceUnavailableException(
                    requester_id=requester_id,
                    reason=str(exc),
                )
