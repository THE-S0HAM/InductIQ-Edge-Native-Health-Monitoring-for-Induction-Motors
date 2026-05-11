"""
Edge health monitor.
Monitors Raspberry Pi system resources and platform health.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Any

import psutil

from edge_platform.config import HealthConfig
from edge_platform.models.device import EdgeHealth
from edge_platform.models.events import Alert, AlertType, Severity

logger = logging.getLogger(__name__)


class EdgeHealthMonitor:
    """
    Monitors the Raspberry Pi edge device health:
    - CPU usage and temperature
    - RAM usage
    - Disk/SD card usage
    - Process health
    - MQTT broker connectivity
    
    Generates alerts when thresholds are exceeded.
    """

    def __init__(self, config: HealthConfig):
        self._config = config
        self._running = False
        self._task: asyncio.Task | None = None
        self._latest_health: EdgeHealth | None = None
        self._boot_time = psutil.boot_time()
        self._alert_callback: Any = None

    def set_alert_callback(self, callback: Any) -> None:
        """Set callback for health alerts."""
        self._alert_callback = callback

    async def start(self) -> None:
        """Start periodic health monitoring."""
        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info("Edge health monitor started (interval=%ds)", self._config.monitor_interval_seconds)

    async def stop(self) -> None:
        """Stop health monitoring."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _monitor_loop(self) -> None:
        """Periodic monitoring loop."""
        while self._running:
            try:
                health = await self._collect_health()
                self._latest_health = health
                
                # Check thresholds and generate alerts
                alerts = self._check_thresholds(health)
                if alerts and self._alert_callback:
                    for alert in alerts:
                        await self._alert_callback(alert)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Health monitor error: %s", e)
            
            await asyncio.sleep(self._config.monitor_interval_seconds)

    async def _collect_health(self) -> EdgeHealth:
        """Collect current system health metrics."""
        # Run in executor to avoid blocking (psutil can be slow)
        loop = asyncio.get_event_loop()
        
        cpu_percent = await loop.run_in_executor(None, psutil.cpu_percent, 1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        temperature = self._get_cpu_temperature()
        
        return EdgeHealth(
            cpu_percent=cpu_percent,
            ram_percent=memory.percent,
            ram_used_mb=memory.used / (1024 * 1024),
            ram_total_mb=memory.total / (1024 * 1024),
            disk_percent=disk.percent,
            disk_used_gb=disk.used / (1024 * 1024 * 1024),
            disk_total_gb=disk.total / (1024 * 1024 * 1024),
            temperature_celsius=temperature,
            process_count=len(psutil.pids()),
            uptime_seconds=time.time() - self._boot_time,
            load_average=os.getloadavg() if hasattr(os, "getloadavg") else None,
        )

    def _get_cpu_temperature(self) -> float | None:
        """Read CPU temperature (Raspberry Pi specific)."""
        # RPi thermal zone
        thermal_path = Path("/sys/class/thermal/thermal_zone0/temp")
        if thermal_path.exists():
            try:
                temp_str = thermal_path.read_text().strip()
                return float(temp_str) / 1000.0  # millidegrees to degrees
            except (ValueError, IOError):
                pass
        
        # Fallback: psutil sensors
        try:
            temps = psutil.sensors_temperatures()
            if temps:
                for name, entries in temps.items():
                    if entries:
                        return entries[0].current
        except (AttributeError, RuntimeError):
            pass
        
        return None

    def _check_thresholds(self, health: EdgeHealth) -> list[Alert]:
        """Check health metrics against configured thresholds."""
        alerts: list[Alert] = []
        
        # CPU
        if health.cpu_percent >= self._config.cpu_critical_percent:
            alerts.append(Alert(
                device_id="EDGE_GATEWAY",
                severity=Severity.CRITICAL,
                alert_type=AlertType.EDGE_RESOURCE_WARNING,
                message=f"CPU critical: {health.cpu_percent:.1f}%",
                metadata={"metric": "cpu", "value": health.cpu_percent},
            ))
        elif health.cpu_percent >= self._config.cpu_warning_percent:
            alerts.append(Alert(
                device_id="EDGE_GATEWAY",
                severity=Severity.WARNING,
                alert_type=AlertType.EDGE_RESOURCE_WARNING,
                message=f"CPU high: {health.cpu_percent:.1f}%",
                metadata={"metric": "cpu", "value": health.cpu_percent},
            ))
        
        # RAM
        if health.ram_percent >= self._config.ram_critical_percent:
            alerts.append(Alert(
                device_id="EDGE_GATEWAY",
                severity=Severity.CRITICAL,
                alert_type=AlertType.EDGE_RESOURCE_WARNING,
                message=f"RAM critical: {health.ram_percent:.1f}% ({health.ram_used_mb:.0f}MB)",
                metadata={"metric": "ram", "value": health.ram_percent},
            ))
        elif health.ram_percent >= self._config.ram_warning_percent:
            alerts.append(Alert(
                device_id="EDGE_GATEWAY",
                severity=Severity.WARNING,
                alert_type=AlertType.EDGE_RESOURCE_WARNING,
                message=f"RAM high: {health.ram_percent:.1f}%",
                metadata={"metric": "ram", "value": health.ram_percent},
            ))
        
        # Disk
        if health.disk_percent >= self._config.disk_critical_percent:
            alerts.append(Alert(
                device_id="EDGE_GATEWAY",
                severity=Severity.CRITICAL,
                alert_type=AlertType.EDGE_RESOURCE_WARNING,
                message=f"Disk critical: {health.disk_percent:.1f}%",
                metadata={"metric": "disk", "value": health.disk_percent},
            ))
        elif health.disk_percent >= self._config.disk_warning_percent:
            alerts.append(Alert(
                device_id="EDGE_GATEWAY",
                severity=Severity.WARNING,
                alert_type=AlertType.EDGE_RESOURCE_WARNING,
                message=f"Disk high: {health.disk_percent:.1f}%",
                metadata={"metric": "disk", "value": health.disk_percent},
            ))
        
        # Temperature
        if health.temperature_celsius is not None:
            if health.temperature_celsius >= self._config.temperature_critical_celsius:
                alerts.append(Alert(
                    device_id="EDGE_GATEWAY",
                    severity=Severity.CRITICAL,
                    alert_type=AlertType.EDGE_RESOURCE_WARNING,
                    message=f"CPU temperature critical: {health.temperature_celsius:.1f}°C",
                    metadata={"metric": "temperature", "value": health.temperature_celsius},
                ))
            elif health.temperature_celsius >= self._config.temperature_warning_celsius:
                alerts.append(Alert(
                    device_id="EDGE_GATEWAY",
                    severity=Severity.WARNING,
                    alert_type=AlertType.EDGE_RESOURCE_WARNING,
                    message=f"CPU temperature high: {health.temperature_celsius:.1f}°C",
                    metadata={"metric": "temperature", "value": health.temperature_celsius},
                ))
        
        return alerts

    def get_latest_health(self) -> EdgeHealth | None:
        """Get the most recent health snapshot."""
        return self._latest_health

    def get_health_dict(self) -> dict[str, Any]:
        """Get health as a dictionary for API responses."""
        if not self._latest_health:
            return {"status": "no_data"}
        return self._latest_health.model_dump()
