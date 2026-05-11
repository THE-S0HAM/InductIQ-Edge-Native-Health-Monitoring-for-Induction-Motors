"""
Cloud API endpoints — serves telemetry data from DynamoDB.
The dashboard fetches from these endpoints.
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from typing import Any

from edge_platform.cloud.dynamo_store import (
    get_all_devices_latest,
    get_latest_reading,
    get_recent_readings,
)

router = APIRouter()


@router.get("/cloud/telemetry/current")
async def cloud_current() -> dict[str, Any]:
    """
    Get latest sensor readings from DynamoDB.
    Primary endpoint for the dashboard — no local DB involved.
    """
    return get_all_devices_latest()


@router.get("/cloud/telemetry/current/{device_id}")
async def cloud_device_current(device_id: str) -> dict[str, Any]:
    """Get latest reading for a specific device from DynamoDB."""
    reading = get_latest_reading(device_id)
    if not reading:
        return {"device_id": device_id, "status": "offline", "telemetry": {}}
    return reading


@router.get("/cloud/telemetry/history/{device_id}")
async def cloud_device_history(
    device_id: str,
    seconds: int = Query(default=300, le=3600),
) -> dict[str, Any]:
    """
    Get recent readings for chart history.
    Returns up to last 5 minutes of data for populating charts on page load.
    """
    readings = get_recent_readings(device_id, seconds)
    return {
        "device_id": device_id,
        "count": len(readings),
        "readings": readings,
    }
