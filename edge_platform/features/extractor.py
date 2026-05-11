"""
Feature extraction engine.
Computes rolling statistics, frequency features, and cross-sensor correlations
from raw telemetry for the AI inference pipeline.
"""

from __future__ import annotations

import logging
import math
import time
from collections import defaultdict, deque
from typing import Any

import numpy as np

from edge_platform.config import InferenceConfig
from edge_platform.models.telemetry import TelemetryMessage

logger = logging.getLogger(__name__)


class RollingBuffer:
    """Memory-efficient circular buffer for time-series data."""

    def __init__(self, maxlen: int = 60):
        self._data: deque[float] = deque(maxlen=maxlen)
        self._timestamps: deque[int] = deque(maxlen=maxlen)

    def append(self, value: float, timestamp: int) -> None:
        self._data.append(value)
        self._timestamps.append(timestamp)

    @property
    def values(self) -> list[float]:
        return list(self._data)

    @property
    def size(self) -> int:
        return len(self._data)

    @property
    def is_full(self) -> bool:
        return len(self._data) == self._data.maxlen

    def mean(self) -> float:
        if not self._data:
            return 0.0
        return sum(self._data) / len(self._data)

    def std(self) -> float:
        if len(self._data) < 2:
            return 0.0
        mean = self.mean()
        variance = sum((x - mean) ** 2 for x in self._data) / (len(self._data) - 1)
        return math.sqrt(variance)

    def min_val(self) -> float:
        return min(self._data) if self._data else 0.0

    def max_val(self) -> float:
        return max(self._data) if self._data else 0.0

    def rate_of_change(self) -> float:
        """Compute rate of change (slope) over the buffer."""
        if len(self._data) < 2:
            return 0.0
        # Simple linear slope
        n = len(self._data)
        x_mean = (n - 1) / 2
        y_mean = self.mean()
        
        numerator = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(self._data))
        denominator = sum((i - x_mean) ** 2 for i in range(n))
        
        if denominator == 0:
            return 0.0
        return numerator / denominator

    def percentile(self, p: float) -> float:
        """Compute percentile (0-100)."""
        if not self._data:
            return 0.0
        sorted_data = sorted(self._data)
        idx = (p / 100) * (len(sorted_data) - 1)
        lower = int(idx)
        upper = min(lower + 1, len(sorted_data) - 1)
        frac = idx - lower
        return sorted_data[lower] * (1 - frac) + sorted_data[upper] * frac


class FeatureExtractor:
    """
    Extracts features from raw telemetry for AI inference.
    
    Maintains per-device, per-sensor rolling buffers and computes:
    - Statistical features (mean, std, min, max, percentiles)
    - Temporal features (rate of change, trend)
    - Vibration features (magnitude, RMS, peak-to-peak)
    - Cross-sensor correlations
    """

    def __init__(self, config: InferenceConfig):
        self._config = config
        self._window_size = config.stages.statistical.window_size
        # Per-device, per-sensor rolling buffers
        self._buffers: dict[str, dict[str, RollingBuffer]] = defaultdict(
            lambda: defaultdict(lambda: RollingBuffer(maxlen=self._window_size))
        )
        self._last_extraction: dict[str, float] = {}

    def update(self, message: TelemetryMessage) -> None:
        """Update rolling buffers with new telemetry."""
        device_id = message.device_id
        payload = message.telemetry
        ts = message.timestamp
        
        # Update scalar sensors
        if payload.temperature is not None:
            self._buffers[device_id]["temperature"].append(payload.temperature, ts)
        if payload.humidity is not None:
            self._buffers[device_id]["humidity"].append(payload.humidity, ts)
        if payload.current is not None:
            self._buffers[device_id]["current"].append(payload.current, ts)
        if payload.pressure is not None:
            self._buffers[device_id]["pressure"].append(payload.pressure, ts)
        if payload.rpm is not None:
            self._buffers[device_id]["rpm"].append(payload.rpm, ts)
        
        # Update vibration
        if payload.vibration:
            vib = payload.vibration
            self._buffers[device_id]["vibration_x"].append(vib.x, ts)
            self._buffers[device_id]["vibration_y"].append(vib.y, ts)
            self._buffers[device_id]["vibration_z"].append(vib.z, ts)
            mag = vib.magnitude or math.sqrt(vib.x**2 + vib.y**2 + vib.z**2)
            self._buffers[device_id]["vibration_magnitude"].append(mag, ts)
        
        # Handle dynamic/extra fields
        if hasattr(payload, "model_extra") and payload.model_extra:
            for key, value in payload.model_extra.items():
                if isinstance(value, (int, float)):
                    self._buffers[device_id][key].append(float(value), ts)

    def extract_features(self, device_id: str) -> dict[str, Any]:
        """
        Extract a complete feature vector for a device.
        Returns a flat dictionary suitable for ML model input.
        """
        features: dict[str, Any] = {}
        device_buffers = self._buffers.get(device_id, {})
        
        if not device_buffers:
            return features
        
        for sensor_name, buffer in device_buffers.items():
            if buffer.size < 3:
                continue
            
            prefix = sensor_name
            
            # Statistical features
            features[f"{prefix}_mean"] = buffer.mean()
            features[f"{prefix}_std"] = buffer.std()
            features[f"{prefix}_min"] = buffer.min_val()
            features[f"{prefix}_max"] = buffer.max_val()
            features[f"{prefix}_range"] = buffer.max_val() - buffer.min_val()
            features[f"{prefix}_p25"] = buffer.percentile(25)
            features[f"{prefix}_p75"] = buffer.percentile(75)
            features[f"{prefix}_iqr"] = buffer.percentile(75) - buffer.percentile(25)
            
            # Temporal features
            features[f"{prefix}_rate_of_change"] = buffer.rate_of_change()
            features[f"{prefix}_latest"] = buffer.values[-1] if buffer.values else 0.0
            
            # Buffer fullness (useful for model confidence)
            features[f"{prefix}_buffer_fill"] = buffer.size / self._window_size
        
        # Cross-sensor features
        features.update(self._compute_cross_features(device_buffers))
        
        # Metadata
        features["_device_id"] = device_id
        features["_timestamp"] = int(time.time())
        features["_feature_count"] = len(features) - 2  # Exclude metadata
        
        self._last_extraction[device_id] = time.time()
        
        return features

    def _compute_cross_features(self, buffers: dict[str, RollingBuffer]) -> dict[str, float]:
        """Compute cross-sensor correlation features."""
        cross: dict[str, float] = {}
        
        # Vibration RMS (if all axes available)
        if all(f"vibration_{ax}" in buffers for ax in ["x", "y", "z"]):
            vx = buffers["vibration_x"].values
            vy = buffers["vibration_y"].values
            vz = buffers["vibration_z"].values
            if vx and vy and vz:
                min_len = min(len(vx), len(vy), len(vz))
                rms = math.sqrt(
                    sum(vx[i]**2 + vy[i]**2 + vz[i]**2 for i in range(min_len)) / min_len
                )
                cross["vibration_rms"] = rms
                
                # Peak-to-peak
                if "vibration_magnitude" in buffers:
                    mag_buf = buffers["vibration_magnitude"]
                    cross["vibration_peak_to_peak"] = mag_buf.max_val() - mag_buf.min_val()
        
        # Thermal-electrical correlation
        if "temperature" in buffers and "current" in buffers:
            temp_rate = buffers["temperature"].rate_of_change()
            curr_rate = buffers["current"].rate_of_change()
            cross["thermal_electrical_correlation"] = temp_rate * curr_rate
        
        # Power indicator
        if "current" in buffers:
            cross["current_rms"] = math.sqrt(
                sum(v**2 for v in buffers["current"].values) / max(buffers["current"].size, 1)
            )
        
        return cross

    def get_buffer_status(self, device_id: str) -> dict[str, int]:
        """Get buffer fill status for a device."""
        device_buffers = self._buffers.get(device_id, {})
        return {name: buf.size for name, buf in device_buffers.items()}

    def has_sufficient_data(self, device_id: str, min_samples: int = 10) -> bool:
        """Check if enough data has been collected for inference."""
        device_buffers = self._buffers.get(device_id, {})
        if not device_buffers:
            return False
        return any(buf.size >= min_samples for buf in device_buffers.values())
