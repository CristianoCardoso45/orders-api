import asyncio

from fastapi import FastAPI, HTTPException

app = FastAPI(title="Requester Mock Service", version="1.0.0")


@app.get("/requesters/{requester_id}")
async def get_requester(requester_id: str) -> dict:
    """
    Returns simulated requester data.

    Args:
        requester_id: ID of the requester to validate.

    Returns:
        Requester data if found.
    """
    if requester_id == "NOT-FOUND":
        raise HTTPException(status_code=404, detail="Requester not found")

    if requester_id == "ERROR":
        raise HTTPException(status_code=500, detail="Internal server error")

    if requester_id == "SLOW":
        await asyncio.sleep(5)

    return {
        "id": requester_id,
        "name": f"Solicitante {requester_id}",
        "active": True,
    }


@app.get("/health")
async def health() -> dict:
    """Mock health check."""
    return {"status": "healthy"}
