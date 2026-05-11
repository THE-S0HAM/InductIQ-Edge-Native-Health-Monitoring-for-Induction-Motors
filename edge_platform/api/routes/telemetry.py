"""Telemetry API endpoints."""

from __future__ import annotations

import time
from fastapi import APIRouter, HTTPException, Query, Request
from typing import Any

from edge_platform.api.routes.live_store import get_all_latest, get_latest

router = APIRouter()


@router.get("/telemetry/current")
async def get_current_readings() -> dict[str, Any]:
    """
    Get current sensor readings directly from memory.
    No database query — instant response with latest MQTT data.
    This is the PRIMARY endpoint for the dashboard.
    """
    return get_all_latest()


@router.get("/telemetry/current/{device_id}")
async def get_current_device(device_id: str) -> dict[str, Any]:
    """Get current reading for a specific device from memory."""
    return get_latest(device_id)


@router.get("/telemetry/live")
async def get_live_sensor_data(request: Request) -> dict[str, Any]:
    """
    Get real-time live reading — now served from in-memory store.
    Kept for backward compatibility with existing dashboard code.
    """
    data = get_all_latest()
    # Reshape to match the old format the dashboard expects
    devices = {}
    for dev_id, dev_data in data.get("devices", {}).items():
        tel = dev_data.get("telemetry", {})
        sensors = {}
        for key, value in tel.items():
            sensors[key] = {"value": value}
        devices[dev_id] = {
            "timestamp": dev_data.get("timestamp"),
            "age_seconds": dev_data.get("age_seconds"),
            "sensors": sensors,
            "status": dev_data.get("status", "offline"),
        }
    return {
        "timestamp": data.get("timestamp", int(time.time())),
        "devices": devices,
        "total_devices": data.get("device_count", 0),
        "live_count": data.get("live_count", 0),
    }


@router.get("/telemetry/{device_id}")
async def get_device_telemetry(
    request: Request,
    device_id: str,
    limit: int = Query(default=100, le=1000),
) -> dict[str, Any]:
    """Get latest telemetry readings for a device from DB."""
    platform = request.app.state.platform
    if not platform:
        raise HTTPException(503, "Platform not initialized")

    data = await platform.storage.get_latest_telemetry(device_id, limit)
    return {"device_id": device_id, "count": len(data), "telemetry": data}


@router.get("/telemetry/{device_id}/range")
async def get_telemetry_range(
    request: Request,
    device_id: str,
    start: int = Query(..., description="Start timestamp (unix)"),
    end: int = Query(..., description="End timestamp (unix)"),
    sensor_type: str | None = Query(default=None),
) -> dict[str, Any]:
    """Get telemetry within a time range from DB."""
    platform = request.app.state.platform
    if not platform:
        raise HTTPException(503, "Platform not initialized")

    data = await platform.storage.get_telemetry_range(device_id, start, end, sensor_type)
    return {"device_id": device_id, "start": start, "end": end, "count": len(data), "data": data}


@router.post("/telemetry/ingest")
async def ingest_telemetry(
    request: Request,
    payload: dict[str, Any],
) -> dict[str, str]:
    """Manually ingest telemetry (for testing/integration)."""
    platform = request.app.state.platform
    if not platform:
        raise HTTPException(503, "Platform not initialized")

    await platform.stream_processor.ingest("api/ingest", payload)
    return {"status": "accepted"}
