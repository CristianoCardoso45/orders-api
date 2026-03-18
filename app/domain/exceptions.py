class DomainException(Exception):
    """Base domain exception. All business exceptions inherit from this one."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(self.message)


class RequesterNotFoundException(DomainException):
    """
    Raised when the requester is not found in the external service (HTTP 404).

    Indicates that the provided requester_id does not correspond to a valid requester,
    therefore the order should not be created.
    """

    def __init__(self, requester_id: str) -> None:
        self.requester_id = requester_id
        super().__init__(f"Requester not found: {requester_id}")


class RequesterServiceUnavailableException(DomainException):
    """
    Raised when the requester service is temporarily unavailable.

    Covers timeout scenarios, HTTP 5xx and connection errors.
    Unlike RequesterNotFoundException, here we do not know if the requester
    is valid. It is an infrastructure error, not a business error.
    """

    def __init__(self, requester_id: str, reason: str) -> None:
        self.requester_id = requester_id
        self.reason = reason
        super().__init__(f"Requester service unavailable for {requester_id}: {reason}")


class DuplicateOrderException(DomainException):
    """
    Raised when a race condition causes a UNIQUE violation on external_order_id.

    Treated as idempotency, the HTTP response will be 200 with the existing order,
    not 409. This ensures that client retries work transparently.
    """

    def __init__(self, external_order_id: str) -> None:
        self.external_order_id = external_order_id
        super().__init__(f"Duplicate order for external_order_id: {external_order_id}")
