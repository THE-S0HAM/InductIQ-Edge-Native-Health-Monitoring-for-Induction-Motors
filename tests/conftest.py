"""Pytest configuration and fixtures."""

import asyncio
import tempfile
from pathlib import Path

import pytest

from edge_platform.config import PlatformConfig, SQLiteConfig, StorageConfig
from edge_platform.storage.sqlite_store import SQLiteStore


@pytest.fixture
def event_loop():
    """Create an event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def temp_db():
    """Create a temporary SQLite database for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        config = SQLiteConfig(path=str(db_path))
        store = SQLiteStore(config)
        await store.initialize()
        yield store
        await store.close()


@pytest.fixture
def test_config():
    """Create a test platform configuration."""
    return PlatformConfig(
        name="Test Platform",
        version="1.0.0",
        site_id="TEST_SITE",
        environment="test",
    )


@pytest.fixture
def sample_telemetry():
    """Sample telemetry message for testing."""
    return {
        "timestamp": 1700000000,
        "device_id": "TEST_MOTOR_001",
        "site_id": "TEST_SITE",
        "telemetry": {
            "temperature": 65.5,
            "humidity": 45.2,
            "current": 3.8,
            "vibration": {
                "x": 1.5,
                "y": 1.2,
                "z": 0.3,
                "magnitude": 1.95,
            },
            "smoke": False,
            "sound": False,
        },
    }


@pytest.fixture
def sample_inference():
    """Sample inference result for testing."""
    return {
        "timestamp": 1700000000,
        "device_id": "TEST_MOTOR_001",
        "fault_class": "normal",
        "confidence": 0.95,
        "health_score": 98.5,
        "scores_json": '{"thermal": 100, "vibration": 95, "electrical": 100}',
        "rul_hours": None,
        "model_version": "1.0.0",
    }
