"""
Alert engine with deduplication, cooldown, and escalation.
Manages the full alert lifecycle from generation to resolution.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Any, Callable, Coroutine

from edge_platform.config import AlertConfig
from edge_platform.models.events import Alert, Severity

logger = logging.getLogger(__name__)

# Type for alert dispatch callbacks
AlertCallback = Callable[[Alert], Coroutine[Any, Any, None]]


class AlertEngine:
    """
    Alert management engine with industrial-grade features:
    - Deduplication (same alert within window is suppressed)
    - Cooldown (minimum time between same alert type per device)
    - Escalation (repeated alerts escalate severity)
    - Suppression rules (configurable suppression)
    - Max active alert limit (prevents alert storms)
    """

    def __init__(self, config: AlertConfig):
        self._config = config
        self._active_alerts: dict[str, Alert] = {}  # alert_id → Alert
        self._cooldowns: dict[str, float] = {}  # dedup_key → last_fired_time
        self._escalation_counts: dict[str, int] = defaultdict(int)
        self._callbacks: list[AlertCallback] = []
        self._suppressed_count = 0
        self._total_fired = 0

    def add_callback(self, callback: AlertCallback) -> None:
        """Register a callback for when alerts are fired."""
        self._callbacks.append(callback)

    async def process_alerts(self, alerts: list[Alert]) -> list[Alert]:
        """
        Process a batch of alerts through dedup/cooldown/escalation.
        Returns the alerts that were actually fired.
        """
        fired: list[Alert] = []
        
        for alert in alerts:
            result = await self._process_single(alert)
            if result:
                fired.append(result)
        
        return fired

    async def _process_single(self, alert: Alert) -> Alert | None:
        """Process a single alert through the pipeline."""
        # Check max active alerts
        if len(self._active_alerts) >= self._config.max_active_alerts:
            # Only allow CRITICAL alerts through during storm
            if alert.severity != Severity.CRITICAL:
                self._suppressed_count += 1
                return None
        
        dedup_key = alert.deduplication_key()
        now = time.time()
        
        # Deduplication check
        if dedup_key in self._cooldowns:
            last_fired = self._cooldowns[dedup_key]
            if (now - last_fired) < self._config.dedup_window_seconds:
                self._suppressed_count += 1
                alert.suppressed = True
                return None
        
        # Cooldown check
        if dedup_key in self._cooldowns:
            last_fired = self._cooldowns[dedup_key]
            if (now - last_fired) < self._config.cooldown_seconds:
                # Within cooldown - check for escalation
                self._escalation_counts[dedup_key] += 1
                
                if self._escalation_counts[dedup_key] >= 3:
                    # Escalate severity
                    alert = self._escalate(alert)
                    alert.escalated = True
                else:
                    self._suppressed_count += 1
                    return None
        
        # Fire the alert
        self._cooldowns[dedup_key] = now
        self._active_alerts[alert.id] = alert
        self._total_fired += 1
        
        # Dispatch to callbacks
        for callback in self._callbacks:
            try:
                await callback(alert)
            except Exception as e:
                logger.error("Alert callback error: %s", e)
        
        logger.info(
            "Alert fired: [%s] %s - %s (device=%s)",
            alert.severity.value,
            alert.alert_type.value,
            alert.message,
            alert.device_id,
        )
        
        return alert

    def _escalate(self, alert: Alert) -> Alert:
        """Escalate alert severity."""
        severity_order = [Severity.INFO, Severity.WARNING, Severity.HIGH, Severity.CRITICAL]
        current_idx = severity_order.index(alert.severity)
        new_idx = min(current_idx + 1, len(severity_order) - 1)
        alert.severity = severity_order[new_idx]
        alert.message = f"[ESCALATED] {alert.message}"
        return alert

    async def acknowledge(self, alert_id: str) -> bool:
        """Acknowledge an active alert."""
        if alert_id in self._active_alerts:
            self._active_alerts[alert_id].acknowledged = True
            return True
        return False

    async def resolve(self, alert_id: str) -> bool:
        """Resolve an active alert."""
        if alert_id in self._active_alerts:
            alert = self._active_alerts[alert_id]
            alert.resolved = True
            alert.resolved_at = int(time.time())
            
            # Reset escalation counter
            dedup_key = alert.deduplication_key()
            self._escalation_counts.pop(dedup_key, None)
            
            # Remove from active
            del self._active_alerts[alert_id]
            return True
        return False

    def get_active_alerts(self, severity: Severity | None = None) -> list[Alert]:
        """Get all active (unresolved) alerts, optionally filtered by severity."""
        alerts = list(self._active_alerts.values())
        if severity:
            alerts = [a for a in alerts if a.severity == severity]
        return sorted(alerts, key=lambda a: a.timestamp, reverse=True)

    def get_alert_counts(self) -> dict[str, int]:
        """Get alert counts by severity."""
        counts: dict[str, int] = {s.value: 0 for s in Severity}
        for alert in self._active_alerts.values():
            counts[alert.severity.value] += 1
        return counts

    def get_stats(self) -> dict[str, Any]:
        """Get engine statistics."""
        return {
            "active_alerts": len(self._active_alerts),
            "total_fired": self._total_fired,
            "suppressed": self._suppressed_count,
            "alert_counts": self.get_alert_counts(),
            "cooldown_entries": len(self._cooldowns),
        }

    async def cleanup_stale(self, max_age_hours: int = 24) -> int:
        """Remove stale alerts older than max_age_hours."""
        cutoff = time.time() - (max_age_hours * 3600)
        stale_ids = [
            aid for aid, alert in self._active_alerts.items()
            if alert.timestamp < cutoff
        ]
        for aid in stale_ids:
            del self._active_alerts[aid]
        return len(stale_ids)
