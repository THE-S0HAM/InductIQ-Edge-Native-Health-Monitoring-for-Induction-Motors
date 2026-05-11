"""
Stage 4: Unknown fault analysis.
Detects and clusters anomalies that don't match known fault patterns.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.neighbors import NearestNeighbors

from edge_platform.config import UnknownFaultStageConfig
from edge_platform.models.inference import FaultClass, UnknownFaultResult

logger = logging.getLogger(__name__)

# Features used for unknown fault detection
ANOMALY_FEATURES = [
    "temperature_mean", "temperature_std",
    "current_mean", "current_std",
    "vibration_magnitude_mean", "vibration_magnitude_std",
    "vibration_rms",
]


class UnknownFaultAnalyzer:
    """
    Detects unknown fault patterns using unsupervised methods.
    
    Uses Isolation Forest for anomaly scoring and nearest-neighbor
    matching against known fault signatures.
    
    When a pattern doesn't match any known fault with sufficient
    confidence, it's flagged as unknown and clustered for later analysis.
    """

    def __init__(self, config: UnknownFaultStageConfig):
        self._config = config
        self._isolation_forest: IsolationForest | None = None
        self._known_signatures: np.ndarray | None = None
        self._known_labels: list[FaultClass] = []
        self._nn_model: NearestNeighbors | None = None
        self._unknown_samples: list[np.ndarray] = []
        self._cluster_counter = 0
        self._initialized = False

    def initialize(self, known_signatures: np.ndarray | None = None, labels: list[str] | None = None) -> None:
        """
        Initialize with known fault signatures for comparison.
        
        Args:
            known_signatures: Array of known fault feature vectors
            labels: Corresponding fault class labels
        """
        # Initialize Isolation Forest (unsupervised)
        self._isolation_forest = IsolationForest(
            contamination=self._config.isolation_contamination,
            n_estimators=50,  # Reduced for RPi performance
            max_samples=256,
            random_state=42,
            n_jobs=1,  # Single thread for RPi
        )
        
        if known_signatures is not None and len(known_signatures) > 0:
            self._known_signatures = known_signatures
            self._known_labels = [FaultClass(l) for l in (labels or [])]
            
            # Fit nearest neighbor model on known signatures
            self._nn_model = NearestNeighbors(n_neighbors=1, metric="euclidean")
            self._nn_model.fit(known_signatures)
            
            # Fit isolation forest on known data
            self._isolation_forest.fit(known_signatures)
        
        self._initialized = True
        logger.info("Unknown fault analyzer initialized")

    def analyze(self, features: dict[str, Any]) -> UnknownFaultResult:
        """
        Analyze features for unknown fault patterns.
        
        Args:
            features: Feature dictionary from FeatureExtractor
            
        Returns:
            UnknownFaultResult indicating if pattern is unknown
        """
        # Extract relevant features
        feature_vector = self._extract_vector(features)
        
        if feature_vector is None:
            return UnknownFaultResult(is_unknown=False)
        
        # Lazy initialization
        if not self._initialized:
            self.initialize()
        
        result = UnknownFaultResult()
        
        # Isolation Forest anomaly score
        if self._isolation_forest is not None:
            try:
                # score_samples returns negative for anomalies
                score = self._isolation_forest.score_samples(feature_vector.reshape(1, -1))
                result.anomaly_score = float(-score[0])  # Invert so higher = more anomalous
                
                # Predict: -1 for anomaly, 1 for normal
                prediction = self._isolation_forest.predict(feature_vector.reshape(1, -1))
                is_anomaly = prediction[0] == -1
            except Exception:
                is_anomaly = False
                result.anomaly_score = 0.0
        else:
            is_anomaly = False
        
        # Nearest known fault matching
        if self._nn_model is not None and self._known_signatures is not None:
            try:
                distances, indices = self._nn_model.kneighbors(
                    feature_vector.reshape(1, -1)
                )
                result.nearest_distance = float(distances[0][0])
                nearest_idx = int(indices[0][0])
                
                if nearest_idx < len(self._known_labels):
                    result.nearest_known_fault = self._known_labels[nearest_idx]
                
                # If distance is large, it's likely unknown
                if result.nearest_distance > 5.0:  # Threshold for "far from known"
                    is_anomaly = True
            except Exception as e:
                logger.debug("Nearest neighbor matching failed: %s", e)
        
        if is_anomaly:
            result.is_unknown = True
            result.cluster_id = self._assign_cluster(feature_vector)
            self._unknown_samples.append(feature_vector)
            
            # Limit stored samples
            if len(self._unknown_samples) > 1000:
                self._unknown_samples = self._unknown_samples[-500:]
        
        return result

    def _extract_vector(self, features: dict[str, Any]) -> np.ndarray | None:
        """Extract feature vector for anomaly detection."""
        values = []
        for feat_name in ANOMALY_FEATURES:
            val = features.get(feat_name)
            if val is None:
                return None  # Missing required feature
            values.append(float(val))
        
        return np.array(values, dtype=np.float64)

    def _assign_cluster(self, vector: np.ndarray) -> int:
        """Assign a cluster ID to an unknown fault pattern."""
        if not self._unknown_samples:
            self._cluster_counter += 1
            return self._cluster_counter
        
        # Simple distance-based clustering
        min_dist = float("inf")
        closest_idx = -1
        
        for i, sample in enumerate(self._unknown_samples[-50:]):  # Check recent samples
            dist = np.linalg.norm(vector - sample)
            if dist < min_dist:
                min_dist = dist
                closest_idx = i
        
        # If close to existing unknown sample, same cluster
        if min_dist < 3.0:
            return closest_idx % 100  # Simple cluster assignment
        
        self._cluster_counter += 1
        return self._cluster_counter

    def get_unknown_fault_count(self) -> int:
        """Get count of unknown fault samples collected."""
        return len(self._unknown_samples)

    def get_stats(self) -> dict[str, Any]:
        """Get analyzer statistics."""
        return {
            "initialized": self._initialized,
            "unknown_samples": len(self._unknown_samples),
            "cluster_count": self._cluster_counter,
            "known_signatures": len(self._known_signatures) if self._known_signatures is not None else 0,
        }
