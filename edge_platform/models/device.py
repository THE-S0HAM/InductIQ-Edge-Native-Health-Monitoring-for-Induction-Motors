"""
Device registry models.
Supports dynamic device registration and management.
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class DeviceStatus(str, Enum):
    """Device operational status."""
    ONLINE = "online"
    OFFLINE = "offline"
    DEGRADED = "degraded"
    MAINTENANCE = "maintenance"
    UNKNOWN = "unknown"


class DeviceType(str, Enum):
    """Supported device types."""
    MOTOR = "motor"
    PUMP = "pump"
    COMPRESSOR = "compressor"
    CONVEYOR = "conveyor"
    GENERATOR = "generator"
    FAN = "fan"
    GEARBOX = "gearbox"
    GENERIC = "generic"


class SensorMetadata(BaseModel):
    """Metadata for a sensor attached to a device."""
    sensor_id: str
    sensor_type: str
    unit: str | None = None
    min_value: float | None = None
    max_value: float | None = None
    sampling_rate_hz: float | None = None
    calibration_offset: float = 0.0
    calibration_scale: float = 1.0
    last_calibration: int | None = None


class Device(BaseModel):
    """A registered industrial device."""
    device_id: str
    site_id: str = "SITE_001"
    device_type: DeviceType = DeviceType.GENERIC
    name: str | None = None
    location: str | None = None
    firmware_version: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    sensors: list[SensorMetadata] = Field(default_factory=list)
    calibration: dict[str, Any] = Field(default_factory=dict)
    last_heartbeat: int | None = None
    status: DeviceStatus = DeviceStatus.UNKNOWN
    registered_at: int = Field(default_factory=lambda: int(time.time()))
    metadata: dict[str, Any] = Field(default_factory=dict)

    def is_online(self, timeout_seconds: int = 180) -> bool:
        """Check if device is considered online based on heartbeat."""
        if self.last_heartbeat is None:
            return False
        return (int(time.time()) - self.last_heartbeat) < timeout_seconds

    def update_heartbeat(self) -> None:
        """Update the last heartbeat timestamp."""
        self.last_heartbeat = int(time.time())
        self.status = DeviceStatus.ONLINE


class EdgeHealth(BaseModel):
    """Edge device (Raspberry Pi) health snapshot."""
    timestamp: int = Field(default_factory=lambda: int(time.time()))
    cpu_percent: float = 0.0
    ram_percent: float = 0.0
    ram_used_mb: float = 0.0
    ram_total_mb: float = 0.0
    disk_percent: float = 0.0
    disk_used_gb: float = 0.0
    disk_total_gb: float = 0.0
    temperature_celsius: float | None = None
    mqtt_latency_ms: float | None = None
    process_count: int = 0
    uptime_seconds: float = 0.0
    load_average: tuple[float, float, float] | None = None
