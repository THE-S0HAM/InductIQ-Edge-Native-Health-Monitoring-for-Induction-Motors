"""Tests for domain models."""

import pytest

from edge_platform.models.telemetry import TelemetryMessage, VibrationReading
from edge_platform.models.inference import InferenceResult, FaultClass
from edge_platform.models.events import Alert, AlertType, Severity


def test_vibration_reading():
    """Test vibration reading model."""
    vib = VibrationReading(x=1.5, y=1.2, z=0.3)
    mag = vib.compute_magnitude()
    
    assert mag > 0
    assert abs(mag - 1.95) < 0.01


def test_telemetry_message(sample_telemetry):
    """Test telemetry message model."""
    msg = TelemetryMessage(**sample_telemetry)
    
    assert msg.device_id == "TEST_MOTOR_001"
    assert msg.telemetry.temperature == 65.5
    assert msg.telemetry.vibration.magnitude == 1.95


def test_telemetry_to_storage_rows(sample_telemetry):
    """Test conversion of telemetry to storage rows."""
    msg = TelemetryMessage(**sample_telemetry)
    rows = msg.to_storage_rows()
    
    assert len(rows) > 0
    assert all("timestamp" in row for row in rows)
    assert all("device_id" in row for row in rows)
    assert all("sensor_type" in row for row in rows)


def test_inference_result():
    """Test inference result model."""
    result = InferenceResult(
        device_id="TEST_MOTOR_001",
        fault_class=FaultClass.BEARING_WEAR,
        confidence=0.85,
    )
    
    assert result.is_anomaly()
    assert result.severity_level() in ["INFO", "WARNING", "HIGH", "CRITICAL"]


def test_alert_model():
    """Test alert model."""
    alert = Alert(
        device_id="TEST_MOTOR_001",
        severity=Severity.WARNING,
        alert_type=AlertType.ANOMALY_DETECTED,
        message="Test anomaly",
    )
    
    assert alert.id is not None
    assert alert.timestamp > 0
    assert not alert.acknowledged
    assert not alert.resolved


def test_alert_deduplication_key():
    """Test alert deduplication key generation."""
    alert = Alert(
        device_id="TEST_MOTOR_001",
        severity=Severity.WARNING,
        alert_type=AlertType.ANOMALY_DETECTED,
        message="Test",
    )
    
    key = alert.deduplication_key()
    assert "TEST_MOTOR_001" in key
    assert "anomaly_detected" in key
    assert "WARNING" in key
