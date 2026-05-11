"""Device registry API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from typing import Any

router = APIRouter()


@router.get("/devices")
async def list_devices(request: Request) -> dict[str, Any]:
    """List all registered devices."""
    platform = request.app.state.platform
    if not platform:
        raise HTTPException(503, "Platform not initialized")
    
    devices = await platform.storage.get_all_devices()
    return {"count": len(devices), "devices": devices}


@router.get("/devices/{device_id}")
async def get_device(request: Request, device_id: str) -> dict[str, Any]:
    """Get device details."""
    platform = request.app.state.platform
    if not platform:
        raise HTTPException(503, "Platform not initialized")
    
    devices = await platform.storage.get_all_devices()
    device = next((d for d in devices if d["device_id"] == device_id), None)
    if not device:
        raise HTTPException(404, f"Device {device_id} not found")
    return device


@router.post("/devices/register")
async def register_device(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    """Register a new device."""
    platform = request.app.state.platform
    if not platform:
        raise HTTPException(503, "Platform not initialized")
    
    required = ["device_id", "site_id"]
    for field in required:
        if field not in payload:
            raise HTTPException(400, f"Missing required field: {field}")
    
    import orjson
    device_data = {
        "device_id": payload["device_id"],
        "site_id": payload.get("site_id", "SITE_001"),
        "device_type": payload.get("device_type", "generic"),
        "name": payload.get("name"),
        "location": payload.get("location"),
        "firmware_version": payload.get("firmware_version"),
        "config_json": orjson.dumps(payload.get("config", {})).decode(),
        "sensors_json": orjson.dumps(payload.get("sensors", [])).decode(),
        "status": "online",
    }
    
    await platform.storage.upsert_device(device_data)
    return {"status": "registered", "device_id": payload["device_id"]}
