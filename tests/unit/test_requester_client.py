import httpx
import pytest
import respx

from app.clients.requester_client import RequesterClient
from app.domain.exceptions import (
    RequesterNotFoundException,
    RequesterServiceUnavailableException,
)

"""
Tests for RequesterClient using respx to intercept httpx calls.

Scope: correct mapping of HTTP responses to domain exceptions.
No real HTTP calls are made.
"""


@pytest.fixture
def client():
    """
    Returns a RequesterClient instance for testing.
    """
    return RequesterClient(base_url="http://mock-service", timeout=1.0)


@respx.mock
async def test_should_return_true_when_requester_exists(client):
    """
    Tests that validate_requester returns True for a 200 HTTP response.
    """
    respx.get("http://mock-service/requesters/REQ-001").respond(status_code=200)

    result = await client.validate_requester("REQ-001")
    assert result is True


@respx.mock
async def test_should_raise_requester_not_found_exception_on_404(client):
    """
    Tests that a 404 HTTP response raises RequesterNotFoundException.
    """
    respx.get("http://mock-service/requesters/NOT-FOUND").respond(status_code=404)

    with pytest.raises(RequesterNotFoundException) as exc_info:
        await client.validate_requester("NOT-FOUND")

    assert exc_info.value.requester_id == "NOT-FOUND"


@respx.mock
async def test_should_raise_service_unavailable_exception_on_500(client):
    """
    Tests that a 500 HTTP response raises RequesterServiceUnavailableException.
    """
    respx.get("http://mock-service/requesters/ERROR").respond(status_code=500)

    with pytest.raises(RequesterServiceUnavailableException):
        await client.validate_requester("ERROR")


@respx.mock
async def test_should_raise_service_unavailable_exception_on_timeout(client):
    """
    Tests that a timeout in the HTTP client raises RequesterServiceUnavailableException.
    """
    respx.get("http://mock-service/requesters/SLOW").mock(
        side_effect=httpx.TimeoutException("Timeout custom")
    )

    with pytest.raises(RequesterServiceUnavailableException) as exc_info:
        await client.validate_requester("SLOW")

    assert "Timeout after" in exc_info.value.reason
    assert not isinstance(exc_info.value, httpx.TimeoutException)


@respx.mock
async def test_should_raise_service_unavailable_on_generic_http_error(client):
    """
    Tests that generic HTTP errors raise RequesterServiceUnavailableException.
    """
    respx.get("http://mock-service/requesters/BAD").mock(
        side_effect=httpx.ConnectError("Connection refused")
    )

    with pytest.raises(RequesterServiceUnavailableException):
        await client.validate_requester("BAD")
