"""
Stage 3: Predictive maintenance engine.
Estimates Remaining Useful Life (RUL) and degradation trends.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

import numpy as np

from edge_platform.config import PredictiveStageConfig
from edge_platform.models.inference import PredictiveResult

logger = logging.getLogger(__name__)


class DegradationTracker:
    """Tracks degradation over time for a single device."""

    def __init__(self, window_hours: int = 168):
        self._max_points = window_hours * 12  # ~5 min intervals
        self._health_history: deque[tuple[float, float]] = deque(maxlen=self._max_points)
        self._fault_counts: dict[str, int] = defaultdict(int)

    def add_health_point(self, timestamp: float, health_score: float) -> None:
        """Record a health score data point."""
        self._health_history.append((timestamp, health_score))

    def add_fault(self, fault_class: str) -> None:
        """Record a fault occurrence."""
        self._fault_counts[fault_class] += 1

    @property
    def data_points(self) -> int:
        return len(self._health_history)

    def compute_degradation_rate(self) -> float:
        """
        Compute degradation rate (health loss per hour).
        Negative = degrading, Positive = improving, Zero = stable.
        """
        if len(self._health_history) < 10:
            return 0.0
        
        points = list(self._health_history)
        n = len(points)
        
        # Linear regression on health vs time
        times = np.array([p[0] for p in points])
        healths = np.array([p[1] for p in points])
        
        # Normalize time to hours
        t0 = times[0]
        times_hours = (times - t0) / 3600.0
        
        if times_hours[-1] - times_hours[0] < 0.1:
            return 0.0
        
        # Simple linear fit
        t_mean = np.mean(times_hours)
        h_mean = np.mean(healths)
        
        numerator = np.sum((times_hours - t_mean) * (healths - h_mean))
        denominator = np.sum((times_hours - t_mean) ** 2)
        
        if denominator == 0:
            return 0.0
        
        slope = numerator / denominator  # health points per hour
        return float(slope)

    def estimate_rul(self, current_health: float, failure_threshold: float = 30.0) -> float | None:
        """
        Estimate Remaining Useful Life in hours.
        Returns None if degradation rate is zero or positive (not degrading).
        """
        rate = self.compute_degradation_rate()
        
        if rate >= 0:
            return None  # Not degrading
        
        # Time until health reaches failure threshold
        health_remaining = current_health - failure_threshold
        if health_remaining <= 0:
            return 0.0  # Already at/below threshold
        
        rul_hours = health_remaining / abs(rate)
        
        # Cap at reasonable maximum
        return min(rul_hours, 8760.0)  # Max 1 year

    def get_trend_direction(self) -> str:
        """Determine if health is improving, stable, or degrading."""
        rate = self.compute_degradation_rate()
        
        if rate > 0.5:
            return "improving"
        elif rate < -0.5:
            return "degrading"
        return "stable"


class PredictiveEngine:
    """
    Predictive maintenance engine.
    
    Tracks degradation curves per device and estimates:
    - Remaining Useful Life (RUL)
    - Degradation rate
    - Trend direction
    - Time to warning/critical thresholds
    """

    def __init__(self, config: PredictiveStageConfig):
        self._config = config
        self._trackers: dict[str, DegradationTracker] = {}
        self._model: Any = None
        self._model_loaded = False

    async def load_model(self) -> None:
        """Load pre-trained RUL estimation model (optional enhancement)."""
        model_path = Path(self._config.rul_model_file)
        
        # The predictive engine works without a model (uses degradation curves)
        # A model enhances accuracy but is not required
        if not model_path.exists():
            logger.info("No RUL model found, using degradation curve estimation")
            return
        
        try:
            import joblib
            loop = asyncio.get_event_loop()
            self._model = await loop.run_in_executor(None, joblib.load, str(model_path))
            self._model_loaded = True
            logger.info("Loaded RUL model from %s", model_path)
        except Exception as e:
            logger.warning("Failed to load RUL model: %s", e)

    def _get_tracker(self, device_id: str) -> DegradationTracker:
        """Get or create a degradation tracker for a device."""
        if device_id not in self._trackers:
            self._trackers[device_id] = DegradationTracker(
                window_hours=self._config.degradation_window_hours
            )
        return self._trackers[device_id]

    async def predict(self, device_id: str, features: dict[str, Any]) -> PredictiveResult:
        """
        Generate predictive maintenance result for a device.
        
        Args:
            device_id: Device identifier
            features: Current feature vector
            
        Returns:
            PredictiveResult with RUL and degradation info
        """
        tracker = self._get_tracker(device_id)
        
        # Compute current health from features
        current_health = self._estimate_current_health(features)
        
        # Record health point
        tracker.add_health_point(time.time(), current_health)
        
        # Compute degradation
        degradation_rate = tracker.compute_degradation_rate()
        trend = tracker.get_trend_direction()
        
        # Estimate RUL
        rul = tracker.estimate_rul(current_health)
        
        # If we have a trained model, use it for enhanced prediction
        if self._model_loaded and tracker.data_points > 50:
            rul = await self._model_predict_rul(device_id, features, tracker)
        
        # Compute time to thresholds
        time_to_warning = None
        time_to_critical = None
        
        if degradation_rate < 0:
            if current_health > 50:
                time_to_warning = (current_health - 50) / abs(degradation_rate)
            if current_health > 30:
                time_to_critical = (current_health - 30) / abs(degradation_rate)
        
        return PredictiveResult(
            rul_hours=rul,
            degradation_rate=degradation_rate,
            trend_direction=trend,
            time_to_warning=time_to_warning,
            time_to_critical=time_to_critical,
        )

    def _estimate_current_health(self, features: dict[str, Any]) -> float:
        """Estimate current health score from features (0-100)."""
        health = 100.0
        
        # Temperature penalty
        temp = features.get("temperature_latest", 0)
        if temp > 60:
            health -= min((temp - 60) * 1.5, 40)
        
        # Vibration penalty
        vib = features.get("vibration_magnitude_mean", 0)
        if vib > 2.0:
            health -= min((vib - 2.0) * 8, 35)
        
        # Current anomaly penalty
        curr_std = features.get("current_std", 0)
        if curr_std > 1.0:
            health -= min(curr_std * 5, 25)
        
        return max(0.0, min(100.0, health))

    async def _model_predict_rul(
        self, device_id: str, features: dict[str, Any], tracker: DegradationTracker
    ) -> float | None:
        """Use trained model for enhanced RUL prediction."""
        try:
            # Prepare model input (degradation history + current features)
            history = list(tracker._health_history)[-100:]
            if len(history) < 10:
                return None
            
            health_values = [h for _, h in history]
            
            model_input = np.array([
                np.mean(health_values),
                np.std(health_values),
                health_values[-1],
                tracker.compute_degradation_rate(),
                features.get("temperature_mean", 0),
                features.get("vibration_magnitude_mean", 0),
                features.get("current_mean", 0),
            ]).reshape(1, -1)
            
            loop = asyncio.get_event_loop()
            prediction = await loop.run_in_executor(
                None, self._model.predict, model_input
            )
            
            return max(0.0, float(prediction[0]))
            
        except Exception as e:
            logger.debug("Model RUL prediction failed: %s", e)
            return None

    def record_fault(self, device_id: str, fault_class: str) -> None:
        """Record a fault event for degradation tracking."""
        tracker = self._get_tracker(device_id)
        tracker.add_fault(fault_class)

    def get_device_summary(self, device_id: str) -> dict[str, Any]:
        """Get degradation summary for a device."""
        tracker = self._trackers.get(device_id)
        if not tracker:
            return {"status": "no_data"}
        
        return {
            "data_points": tracker.data_points,
            "degradation_rate": tracker.compute_degradation_rate(),
            "trend": tracker.get_trend_direction(),
            "fault_counts": dict(tracker._fault_counts),
        }
