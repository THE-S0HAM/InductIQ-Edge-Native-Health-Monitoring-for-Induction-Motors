"""
Stage 1: Statistical anomaly detection.
Fast, lightweight detection using z-scores, EWMA, and adaptive thresholds.
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from typing import Any

from edge_platform.config import StatisticalStageConfig
from edge_platform.models.inference import StatisticalResult

logger = logging.getLogger(__name__)


class StatisticalDetector:
    """
    Statistical anomaly detector using multiple methods:
    - Z-score detection (deviation from rolling mean)
    - EWMA (Exponentially Weighted Moving Average) for trend detection
    - IQR-based outlier detection
    - Adaptive thresholds that learn normal operating ranges
    """

    def __init__(self, config: StatisticalStageConfig):
        self._config = config
        self._ewma: dict[str, float] = defaultdict(float)
        self._ewma_var: dict[str, float] = defaultdict(float)
        self._initialized: dict[str, bool] = defaultdict(bool)

    def detect(self, features: dict[str, Any]) -> StatisticalResult:
        """
        Run statistical anomaly detection on extracted features.
        
        Args:
            features: Feature dictionary from FeatureExtractor
            
        Returns:
            StatisticalResult with anomaly flags and scores
        """
        anomaly_scores: dict[str, float] = {}
        z_scores: dict[str, float] = {}
        violations: list[str] = []
        
        # Check each sensor's statistical features
        sensor_prefixes = set()
        for key in features:
            if key.startswith("_"):
                continue
            parts = key.rsplit("_", 1)
            if len(parts) == 2 and parts[1] in ("mean", "std", "latest", "rate_of_change"):
                sensor_prefixes.add(parts[0])
        
        for sensor in sensor_prefixes:
            mean = features.get(f"{sensor}_mean", 0.0)
            std = features.get(f"{sensor}_std", 0.0)
            latest = features.get(f"{sensor}_latest", 0.0)
            
            if std == 0:
                continue
            
            # Z-score detection
            z = abs(latest - mean) / std if std > 0 else 0.0
            z_scores[sensor] = z
            
            if z > self._config.z_score_threshold:
                violations.append(sensor)
                anomaly_scores[sensor] = min(z / self._config.z_score_threshold, 3.0)
            else:
                anomaly_scores[sensor] = z / self._config.z_score_threshold
            
            # EWMA detection
            ewma_key = sensor
            if not self._initialized[ewma_key]:
                self._ewma[ewma_key] = latest
                self._ewma_var[ewma_key] = std ** 2
                self._initialized[ewma_key] = True
            else:
                alpha = self._config.ewma_alpha
                self._ewma[ewma_key] = alpha * latest + (1 - alpha) * self._ewma[ewma_key]
                diff = latest - self._ewma[ewma_key]
                self._ewma_var[ewma_key] = (
                    alpha * diff ** 2 + (1 - alpha) * self._ewma_var[ewma_key]
                )
                
                ewma_std = math.sqrt(self._ewma_var[ewma_key])
                if ewma_std > 0:
                    ewma_z = abs(diff) / ewma_std
                    if ewma_z > self._config.z_score_threshold * 0.8:
                        if sensor not in violations:
                            violations.append(f"{sensor}_trend")
                        anomaly_scores[sensor] = max(
                            anomaly_scores.get(sensor, 0),
                            ewma_z / self._config.z_score_threshold,
                        )
            
            # IQR-based detection
            iqr = features.get(f"{sensor}_iqr", 0.0)
            p25 = features.get(f"{sensor}_p25", 0.0)
            p75 = features.get(f"{sensor}_p75", 0.0)
            
            if iqr > 0:
                lower_fence = p25 - 1.5 * iqr
                upper_fence = p75 + 1.5 * iqr
                
                if latest < lower_fence or latest > upper_fence:
                    if sensor not in violations:
                        violations.append(sensor)
                    # Boost anomaly score
                    distance = max(lower_fence - latest, latest - upper_fence, 0)
                    iqr_score = distance / iqr if iqr > 0 else 0
                    anomaly_scores[sensor] = max(
                        anomaly_scores.get(sensor, 0),
                        min(iqr_score, 3.0),
                    )
        
        # Rate of change detection (sudden spikes)
        for sensor in sensor_prefixes:
            roc = features.get(f"{sensor}_rate_of_change", 0.0)
            if abs(roc) > 2.0:  # Significant rate of change
                if sensor not in violations:
                    violations.append(f"{sensor}_roc")
                anomaly_scores[f"{sensor}_roc"] = min(abs(roc), 5.0)
        
        is_anomaly = len(violations) > 0
        
        return StatisticalResult(
            is_anomaly=is_anomaly,
            anomaly_scores=anomaly_scores,
            z_scores=z_scores,
            threshold_violations=violations,
        )
