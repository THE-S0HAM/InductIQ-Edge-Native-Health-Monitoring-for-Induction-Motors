"""
MQTT topic hierarchy management.
Provides structured topic generation for the industrial IoT namespace.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TopicBuilder:
    """Builds MQTT topics following the industrial hierarchy."""
    
    prefix: str = "iiot"
    site_id: str = "SITE_001"

    def device_telemetry(self, device_id: str) -> str:
        return f"{self.prefix}/site/{self.site_id}/device/{device_id}/telemetry"

    def device_inference(self, device_id: str) -> str:
        return f"{self.prefix}/site/{self.site_id}/device/{device_id}/inference"

    def device_alerts(self, device_id: str) -> str:
        return f"{self.prefix}/site/{self.site_id}/device/{device_id}/alerts"

    def device_alerts_critical(self, device_id: str) -> str:
        return f"{self.prefix}/site/{self.site_id}/device/{device_id}/alerts/critical"

    def device_health(self, device_id: str) -> str:
        return f"{self.prefix}/site/{self.site_id}/device/{device_id}/health"

    def device_events(self, device_id: str) -> str:
        return f"{self.prefix}/site/{self.site_id}/device/{device_id}/events"

    def device_config(self, device_id: str) -> str:
        return f"{self.prefix}/site/{self.site_id}/device/{device_id}/config"

    def system_health(self) -> str:
        return f"{self.prefix}/system/health"

    # Wildcard subscriptions
    def all_device_telemetry(self) -> str:
        return f"{self.prefix}/site/{self.site_id}/device/+/telemetry"

    def all_device_health(self) -> str:
        return f"{self.prefix}/site/{self.site_id}/device/+/health"

    def all_device_events(self) -> str:
        return f"{self.prefix}/site/{self.site_id}/device/+/events"
