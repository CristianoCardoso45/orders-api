import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class CreateOrderRequest(BaseModel):
    """
    Input payload for order creation.

    All fields are required to ensure complete data
    on creation. Validation is performed by Pydantic before reaching the service.
    """

    external_order_id: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="External order identifier (idempotency key)",
        examples=["ORD-2024-001"],
    )
    requester_id: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="ID of the requester to be validated in the external service",
        examples=["REQ-001"],
    )
    description: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Service order description",
        examples=["Preventive maintenance on equipment X"],
    )


class OrderResponse(BaseModel):
    """Response with data of the created or retrieved order (idempotency)."""

    id: uuid.UUID
    external_order_id: str
    requester_id: str
    description: str
    status: str
    created_at: datetime


class ErrorResponse(BaseModel):
    """
    Standardized error response.

    Always includes correlation_id for traceability, the client can
    report this ID to support to facilitate investigation.
    """

    detail: str
    correlation_id: str
