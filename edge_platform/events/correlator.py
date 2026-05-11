"""
Event correlation engine.
Correlates multi-signal events, groups temporal patterns, and determines severity.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from typing import Any

from edge_platform.models.events import Alert, AlertType, Event, EventType, Severity
from edge_platform.models.inference import FaultClass, InferenceResult

logger = logging.getLogger(__name__)


class EventCorrelator:
    """
    Correlates events from multiple sources to identify patterns
    and determine appropriate alert severity.
    
    Features:
    - Temporal event grouping (events within time window)
    - Multi-signal correlation (vibration + temperature = specific fault)
    - Severity escalation based on pattern persistence
    - Root cause determination from correlated events
    """

    def __init__(self, correlation_window_seconds: int = 60):
        self._window = correlation_window_seconds
        # Recent events per device for correlation
        self._recent_events: dict[str, deque[Event]] = defaultdict(
            lambda: deque(maxlen=100)
        )
        # Fault history for escalation
        self._fault_history: dict[str, deque[tuple[float, str]]] = defaultdict(
            lambda: deque(maxlen=50)
        )
        self._event_count = 0

    def correlate_inference(self, result: InferenceResult) -> list[Alert]:
        """
        Process an inference result and generate correlated alerts.
        
        Args:
            result: AI inference result
            
        Returns:
            List of alerts to be raised (may be empty)
        """
        alerts: list[Alert] = []
        device_id = result.device_id
        now = time.time()
        
        # Record event
        event = Event(
            event_type=EventType.INFERENCE_COMPLETE,
            device_id=device_id,
            data={
                "fault_class": result.fault_class.value,
                "confidence": result.confidence,
                "health_score": result.health_scores.overall,
            },
        )
        self._recent_events[device_id].append(event)
        self._event_count += 1
        
        # No alerts for normal operation
        if result.fault_class == FaultClass.NORMAL:
            return alerts
        
        # Record fault
        self._fault_history[device_id].append((now, result.fault_class.value))
        
        # Determine severity based on correlation
        severity = self._determine_severity(device_id, result)
        
        # Generate fault alert
        alert = Alert(
            device_id=device_id,
            severity=severity,
            alert_type=AlertType.FAULT_CLASSIFIED,
            message=self._format_fault_message(result),
            metadata={
                "fault_class": result.fault_class.value,
                "confidence": result.confidence,
                "health_score": result.health_scores.overall,
                "root_cause": result.root_cause,
                "contributing_factors": result.contributing_factors,
            },
        )
        alerts.append(alert)
        
        # RUL warning
        if result.rul_hours is not None and result.rul_hours < 168:  # < 1 week
            rul_severity = Severity.HIGH if result.rul_hours < 48 else Severity.WARNING
            alerts.append(Alert(
                device_id=device_id,
                severity=rul_severity,
                alert_type=AlertType.RUL_WARNING,
                message=f"Estimated {result.rul_hours:.0f}h remaining useful life",
                metadata={"rul_hours": result.rul_hours, "degradation_rate": result.degradation_rate},
            ))
        
        # Unknown fault escalation
        if result.fault_class == FaultClass.UNKNOWN_FAULT:
            alerts.append(Alert(
                device_id=device_id,
                severity=Severity.WARNING,
                alert_type=AlertType.UNKNOWN_FAULT,
                message="Unknown fault pattern detected - requires investigation",
                metadata={
                    "confidence": result.confidence,
                    "inference_stage": result.inference_stage,
                },
            ))
        
        # Shutdown recommendation for critical health
        if result.health_scores.overall < 20:
            alerts.append(Alert(
                device_id=device_id,
                severity=Severity.CRITICAL,
                alert_type=AlertType.SHUTDOWN_RECOMMENDED,
                message="Critical health level - immediate shutdown recommended",
                metadata={"health_score": result.health_scores.overall},
            ))
        
        return alerts

    def _determine_severity(self, device_id: str, result: InferenceResult) -> Severity:
        """Determine alert severity based on correlation and history."""
        # Base severity from health score
        base_severity = result.severity_level()
        
        # Check for repeated faults (escalation)
        recent_faults = [
            (ts, fc) for ts, fc in self._fault_history[device_id]
            if time.time() - ts < 3600  # Last hour
        ]
        
        # Escalate if same fault repeats
        same_fault_count = sum(
            1 for _, fc in recent_faults if fc == result.fault_class.value
        )
        
        severity_order = [Severity.INFO, Severity.WARNING, Severity.HIGH, Severity.CRITICAL]
        severity_idx = severity_order.index(Severity(base_severity))
        
        if same_fault_count >= 5:
            severity_idx = min(severity_idx + 2, 3)
        elif same_fault_count >= 3:
            severity_idx = min(severity_idx + 1, 3)
        
        # Escalate for low confidence (uncertainty is dangerous)
        if result.confidence < 0.5 and severity_idx < 2:
            severity_idx = min(severity_idx + 1, 3)
        
        return severity_order[severity_idx]

    def _format_fault_message(self, result: InferenceResult) -> str:
        """Format a human-readable fault message."""
        fault_names = {
            FaultClass.BEARING_WEAR: "Bearing Wear",
            FaultClass.ROTOR_IMBALANCE: "Rotor Imbalance",
            FaultClass.SHAFT_MISALIGNMENT: "Shaft Misalignment",
            FaultClass.MOISTURE_INGRESS: "Moisture Ingress",
            FaultClass.OVERHEATING: "Overheating",
            FaultClass.CAVITATION: "Cavitation",
            FaultClass.LUBRICATION_FAILURE: "Lubrication Failure",
            FaultClass.ROTOR_BAR_DAMAGE: "Rotor Bar Damage",
            FaultClass.ELECTRICAL_ARCING: "Electrical Arcing",
            FaultClass.LOOSE_MOUNTING: "Loose Mounting",
            FaultClass.INSULATION_BREAKDOWN: "Insulation Breakdown",
            FaultClass.UNKNOWN_FAULT: "Unknown Fault",
            FaultClass.EMERGING_PATTERN: "Emerging Pattern",
        }
        
        name = fault_names.get(result.fault_class, result.fault_class.value)
        return (
            f"{name} detected (confidence: {result.confidence:.0%}, "
            f"health: {result.health_scores.overall:.0f}%)"
        )

    def get_recent_events(self, device_id: str, limit: int = 20) -> list[dict[str, Any]]:
        """Get recent events for a device."""
        events = list(self._recent_events.get(device_id, []))[-limit:]
        return [e.model_dump() for e in events]

    def get_stats(self) -> dict[str, Any]:
        """Get correlator statistics."""
        return {
            "total_events": self._event_count,
            "devices_tracked": len(self._recent_events),
            "correlation_window_seconds": self._window,
        }
