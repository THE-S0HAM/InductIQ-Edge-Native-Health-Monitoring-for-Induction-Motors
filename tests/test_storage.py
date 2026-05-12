"""Tests for storage layer."""

import pytest

from edge_platform.storage.sqlite_store import SQLiteStore


@pytest.mark.asyncio
async def test_storage_initialization(temp_db):
    """Test that storage initializes correctly."""
    assert temp_db is not None
    counts = await temp_db.get_table_counts()
    assert "telemetry" in counts
    assert "inference_results" in counts
    assert "alerts" in counts


@pytest.mark.asyncio
async def test_insert_telemetry(temp_db, sample_telemetry):
    """Test telemetry insertion."""
    from edge_platform.models.telemetry import TelemetryMessage
    
    msg = TelemetryMessage(**sample_telemetry)
    rows = msg.to_storage_rows()
    
    await temp_db.insert_telemetry(rows)
    
    retrieved = await temp_db.get_latest_telemetry("TEST_MOTOR_001", limit=10)
    assert len(retrieved) > 0
    assert retrieved[0]["device_id"] == "TEST_MOTOR_001"


@pytest.mark.asyncio
async def test_insert_inference(temp_db, sample_inference):
    """Test inference result insertion."""
    await temp_db.insert_inference(sample_inference)
    
    result = await temp_db.get_latest_inference("TEST_MOTOR_001")
    assert result is not None
    assert result["device_id"] == "TEST_MOTOR_001"
    assert result["fault_class"] == "normal"


@pytest.mark.asyncio
async def test_alert_lifecycle(temp_db):
    """Test alert insertion, acknowledgment, and resolution."""
    alert = {
        "alert_id": "TEST_ALERT_001",
        "timestamp": 1700000000,
        "device_id": "TEST_MOTOR_001",
        "severity": "WARNING",
        "alert_type": "anomaly_detected",
        "message": "Test alert",
        "metadata_json": "{}",
    }
    
    await temp_db.insert_alert(alert)
    
    alerts = await temp_db.get_active_alerts()
    assert len(alerts) > 0
    
    await temp_db.acknowledge_alert("TEST_ALERT_001")
    await temp_db.resolve_alert("TEST_ALERT_001")
