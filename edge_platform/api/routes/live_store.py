"""
In-memory live sensor data store.
Holds the latest telemetry reading per device — no database involved.
The browser fetches directly from this store via /api/v1/telemetry/current.
"""

from __future__ import annotations

import time
from typing import Any

# In-memory store: device_id -> latest full telemetry payload
_latest_readings: dict[str, dict[str, Any]] = {}


def update_reading(device_id: str, timestamp: int, telemetry: dict[str, Any]) -> None:
    """
    Called whenever new sensor data arrives (from MQTT/stream processor).
    Stores the complete telemetry payload in memory.
    """
    _latest_readings[device_id] = {
        "device_id": device_id,
        "timestamp": timestamp,
        "telemetry": telemetry,
        "received_at": time.time(),
    }


def get_latest(device_id: str | None = None) -> dict[str, Any]:
    """
    Get latest readings. If device_id is None, returns all devices.
    """
    now = time.time()

    if device_id:
        entry = _latest_readings.get(device_id)
        if not entry:
            return {"device_id": device_id, "status": "offline", "telemetry": {}}
        age = now - entry["received_at"]
        return {
            "device_id": device_id,
            "status": "live" if age < 30 else "stale",
            "timestamp": entry["timestamp"],
            "age_seconds": round(age, 1),
            "telemetry": entry["telemetry"],
        }

    # All devices
    result = {}
    for dev_id, entry in _latest_readings.items():
        age = now - entry["received_at"]
        result[dev_id] = {
            "status": "live" if age < 30 else "stale",
            "timestamp": entry["timestamp"],
            "age_seconds": round(age, 1),
            "telemetry": entry["telemetry"],
        }
    return result


def get_all_latest() -> dict[str, Any]:
    """Get all device readings formatted for the dashboard."""
    now = time.time()
    devices = {}

    for dev_id, entry in _latest_readings.items():
        age = now - entry["received_at"]
        devices[dev_id] = {
            "status": "live" if age < 30 else "stale",
            "timestamp": entry["timestamp"],
            "age_seconds": round(age, 1),
            "telemetry": entry["telemetry"],
        }

    return {
        "timestamp": int(now),
        "devices": devices,
        "device_count": len(devices),
        "live_count": sum(1 for d in devices.values() if d["status"] == "live"),
    }
