"""Tests for feature extraction."""

import pytest

from edge_platform.config import InferenceConfig
from edge_platform.features.extractor import FeatureExtractor, RollingBuffer
from edge_platform.models.telemetry import TelemetryMessage


def test_rolling_buffer():
    """Test rolling buffer statistics."""
    buf = RollingBuffer(maxlen=10)
    
    for i in range(10):
        buf.append(float(i), i)
    
    assert buf.size == 10
    assert buf.is_full
    assert buf.mean() == 4.5
    assert buf.min_val() == 0.0
    assert buf.max_val() == 9.0


def test_rolling_buffer_percentile():
    """Test percentile calculation."""
    buf = RollingBuffer(maxlen=100)
    
    for i in range(100):
        buf.append(float(i), i)
    
    p25 = buf.percentile(25)
    p75 = buf.percentile(75)
    
    assert 20 < p25 < 30
    assert 70 < p75 < 80


def test_feature_extractor_initialization():
    """Test feature extractor initialization."""
    config = InferenceConfig()
    extractor = FeatureExtractor(config)
    
    assert extractor is not None
    assert extractor._window_size == 60


def test_feature_extraction(sample_telemetry):
    """Test feature extraction from telemetry."""
    config = InferenceConfig()
    extractor = FeatureExtractor(config)
    
    msg = TelemetryMessage(**sample_telemetry)
    extractor.update(msg)
    
    features = extractor.extract_features("TEST_MOTOR_001")
    
    assert "_device_id" in features
    assert "_timestamp" in features
    assert "_feature_count" in features


def test_feature_extraction_multiple_readings(sample_telemetry):
    """Test feature extraction with multiple readings."""
    config = InferenceConfig()
    extractor = FeatureExtractor(config)
    
    # Feed multiple readings
    for i in range(20):
        msg = TelemetryMessage(**sample_telemetry)
        msg.timestamp += i
        extractor.update(msg)
    
    features = extractor.extract_features("TEST_MOTOR_001")
    
    # Should have computed statistics
    assert "temperature_mean" in features
    assert "temperature_std" in features
    assert "vibration_magnitude_mean" in features


def test_buffer_status():
    """Test buffer status reporting."""
    config = InferenceConfig()
    extractor = FeatureExtractor(config)
    
    status = extractor.get_buffer_status("TEST_MOTOR_001")
    assert isinstance(status, dict)


def test_sufficient_data_check(sample_telemetry):
    """Test sufficient data check."""
    config = InferenceConfig()
    extractor = FeatureExtractor(config)
    
    # Initially no data
    assert not extractor.has_sufficient_data("TEST_MOTOR_001")
    
    # Add some readings
    for i in range(15):
        msg = TelemetryMessage(**sample_telemetry)
        msg.timestamp += i
        extractor.update(msg)
    
    # Should have sufficient data now
    assert extractor.has_sufficient_data("TEST_MOTOR_001", min_samples=10)
