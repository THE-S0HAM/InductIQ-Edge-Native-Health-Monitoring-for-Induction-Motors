"""
Telemetry data models.
Supports dynamic sensor schemas with flexible payloads.
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class SensorQuality(int, Enum):
    """Sensor reading quality indicator."""
    GOOD = 100
    DEGRADED = 75
    SUSPECT = 50
    BAD = 25
    OFFLINE = 0


class VibrationReading(BaseModel):
    """3-axis vibration measurement."""
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    magnitude: float | None = None

    def compute_magnitude(self) -> float:
        """Compute vibration magnitude from axes."""
        import math
        self.magnitude = math.sqrt(self.x**2 + self.y**2 + self.z**2)
        return self.magnitude


class TelemetryPayload(BaseModel):
    """
    Flexible telemetry payload supporting dynamic sensor schemas.
    Known fields are typed; unknown fields pass through via extra.
    """
    temperature: float | None = None
    humidity: float | None = None
    current: float | None = None
    vibration: VibrationReading | None = None
    smoke: bool | None = None
    sound: bool | None = None
    pressure: float | None = None
    rpm: float | None = None
    power: float | None = None
    
    class Config:
        extra = "allow"  # Support dynamic/unknown sensor fields


class TelemetryMessage(BaseModel):
    """Complete telemetry message from a device."""
    timestamp: int = Field(default_factory=lambda: int(time.time()))
    device_id: str
    site_id: str = "SITE_001"
    telemetry: TelemetryPayload
    quality: SensorQuality = SensorQuality.GOOD
    sequence: int | None = None
    metadata: dict[str, Any] | None = None

    def to_storage_rows(self) -> list[dict[str, Any]]:
        """Convert to flat rows for storage insertion."""
        rows = []
        payload = self.telemetry.model_dump(exclude_none=True)
        
        for sensor_type, value in payload.items():
            if isinstance(value, dict):
                # Nested sensor (e.g., vibration)
                import orjson
                value_json = orjson.dumps(value).decode()
            else:
                import orjson
                value_json = orjson.dumps(value).decode()
            
            rows.append({
                "timestamp": self.timestamp,
                "device_id": self.device_id,
                "sensor_type": sensor_type,
                "value_json": value_json,
                "quality": self.quality.value,
            })
        
        return rows
