"""
Multi-stage AI inference pipeline.
Orchestrates statistical detection → classification → prediction → unknown fault analysis.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from edge_platform.ai.statistical import StatisticalDetector
from edge_platform.ai.classifier import FaultClassifier
from edge_platform.ai.predictive import PredictiveEngine
from edge_platform.ai.unknown_fault import UnknownFaultAnalyzer
from edge_platform.config import InferenceConfig
from edge_platform.features.extractor import FeatureExtractor
from edge_platform.models.inference import (
    FaultClass,
    HealthScores,
    InferenceResult,
)
from edge_platform.models.telemetry import TelemetryMessage

logger = logging.getLogger(__name__)


class InferencePipeline:
    """
    Multi-stage AI inference pipeline for industrial fault detection.
    
    Stages:
    1. Statistical: Fast anomaly detection via z-scores and thresholds
    2. Classification: ML-based fault type identification
    3. Predictive: RUL estimation and degradation analysis
    4. Unknown Fault: Clustering for unrecognized patterns
    
    Only inference is performed on-device. Training happens externally.
    """

    def __init__(self, config: InferenceConfig, feature_extractor: FeatureExtractor):
        self._config = config
        self._feature_extractor = feature_extractor
        
        # Initialize stages
        self._statistical = StatisticalDetector(config.stages.statistical)
        self._classifier = FaultClassifier(config)
        self._predictive = PredictiveEngine(config.stages.predictive)
        self._unknown_fault = UnknownFaultAnalyzer(config.stages.unknown_fault)
        
        # Inference state
        self._last_inference: dict[str, float] = {}
        self._inference_count = 0
        self._semaphore = asyncio.Semaphore(config.max_concurrent_inferences)
        self._models_loaded = False

    async def initialize(self) -> None:
        """Mark pipeline as ready. Models load lazily on first inference."""
        logger.info("AI pipeline ready (lazy loading, model_dir=%s)", self._config.model_dir)

    async def _ensure_models_loaded(self) -> None:
        """Load models on first inference call (lazy initialization)."""
        if self._models_loaded:
            return
        logger.info("Loading AI models (first inference)...")
        await self._classifier.load_model()
        await self._predictive.load_model()
        self._models_loaded = True
        logger.info("AI models loaded")

    async def process(self, message: TelemetryMessage) -> InferenceResult | None:
        """
        Run the full inference pipeline on a telemetry message.
        Returns None if inference is not needed (rate limiting).
        """
        device_id = message.device_id
        now = time.time()
        
        # Rate limit inference per device
        last = self._last_inference.get(device_id, 0)
        if (now - last) < self._config.inference_interval_seconds:
            return None
        
        # Check if we have enough data
        if not self._feature_extractor.has_sufficient_data(device_id):
            return None
        
        # Acquire semaphore (limit concurrent inferences for CPU)
        async with self._semaphore:
            start_time = time.time()
            result = await self._run_pipeline(device_id)
            result.processing_time_ms = (time.time() - start_time) * 1000
            
            self._last_inference[device_id] = now
            self._inference_count += 1
            
            return result

    async def _run_pipeline(self, device_id: str) -> InferenceResult:
        """Execute the multi-stage pipeline."""
        # Lazy load models on first real inference
        await self._ensure_models_loaded()
        
        # Extract features
        features = self._feature_extractor.extract_features(device_id)
        
        # Stage 1: Statistical detection
        stat_result = self._statistical.detect(features)
        
        result = InferenceResult(
            device_id=device_id,
            inference_stage="statistical",
        )
        
        if not stat_result.is_anomaly:
            # No anomaly - compute health scores and return
            result.health_scores = self._compute_health_scores(features)
            result.fault_class = FaultClass.NORMAL
            result.confidence = 1.0 - max(stat_result.anomaly_scores.values(), default=0.0)
            return result
        
        # Stage 2: Fault classification
        if self._config.stages.classification.enabled:
            class_result = await self._classifier.classify(features)
            result.fault_class = class_result.fault_class
            result.confidence = class_result.confidence
            result.inference_stage = "classification"
            
            # Stage 3: Predictive maintenance
            if self._config.stages.predictive.enabled:
                pred_result = await self._predictive.predict(device_id, features)
                result.rul_hours = pred_result.rul_hours
                result.degradation_rate = pred_result.degradation_rate
                result.trend_direction = pred_result.trend_direction
                result.inference_stage = "predictive"
            
            # Stage 4: Unknown fault (if low confidence)
            if (
                self._config.stages.unknown_fault.enabled
                and class_result.confidence < self._config.unknown_fault_threshold
            ):
                unknown_result = self._unknown_fault.analyze(features)
                if unknown_result.is_unknown:
                    result.fault_class = FaultClass.UNKNOWN_FAULT
                    result.inference_stage = "unknown"
                    result.root_cause = f"Unknown pattern (cluster {unknown_result.cluster_id})"
        
        # Compute health scores
        result.health_scores = self._compute_health_scores(features, stat_result.anomaly_scores)
        
        # Determine root cause
        if result.fault_class != FaultClass.NORMAL and not result.root_cause:
            result.root_cause = self._determine_root_cause(
                result.fault_class, stat_result.threshold_violations
            )
            result.contributing_factors = stat_result.threshold_violations
        
        return result

    def _compute_health_scores(
        self, features: dict[str, Any], anomaly_scores: dict[str, float] | None = None
    ) -> HealthScores:
        """Compute component health scores from features and anomaly scores."""
        scores = HealthScores()
        
        if anomaly_scores is None:
            anomaly_scores = {}
        
        # Thermal health
        temp_score = anomaly_scores.get("temperature", 0.0)
        scores.thermal = max(0, 100 - (temp_score * 30))
        
        # Vibration health
        vib_score = anomaly_scores.get("vibration_magnitude", 0.0)
        scores.vibration = max(0, 100 - (vib_score * 25))
        
        # Electrical health
        curr_score = anomaly_scores.get("current", 0.0)
        scores.electrical = max(0, 100 - (curr_score * 25))
        
        # Overall (weighted average)
        scores.overall = (
            scores.thermal * 0.25
            + scores.vibration * 0.30
            + scores.electrical * 0.25
            + scores.smoke * 0.10
            + scores.acoustic * 0.10
        )
        
        return scores

    def _determine_root_cause(
        self, fault_class: FaultClass, violations: list[str]
    ) -> str:
        """Determine probable root cause based on fault class and violations."""
        root_causes = {
            FaultClass.BEARING_WEAR: "Bearing degradation detected via vibration pattern",
            FaultClass.ROTOR_IMBALANCE: "Rotor mass imbalance causing periodic vibration",
            FaultClass.SHAFT_MISALIGNMENT: "Shaft angular/parallel misalignment",
            FaultClass.MOISTURE_INGRESS: "Moisture detected in motor housing",
            FaultClass.OVERHEATING: "Thermal runaway - excessive temperature rise",
            FaultClass.CAVITATION: "Fluid cavitation in pump/impeller",
            FaultClass.LUBRICATION_FAILURE: "Insufficient lubrication causing friction",
            FaultClass.ROTOR_BAR_DAMAGE: "Broken rotor bar detected via current signature",
            FaultClass.ELECTRICAL_ARCING: "Electrical arcing in windings/connections",
            FaultClass.LOOSE_MOUNTING: "Mechanical looseness in mounting/foundation",
            FaultClass.INSULATION_BREAKDOWN: "Winding insulation degradation",
            FaultClass.UNKNOWN_FAULT: "Unrecognized fault pattern - requires investigation",
            FaultClass.EMERGING_PATTERN: "New degradation pattern emerging",
        }
        return root_causes.get(fault_class, "Unknown root cause")

    def get_stats(self) -> dict[str, Any]:
        """Get pipeline statistics."""
        return {
            "inference_count": self._inference_count,
            "devices_tracked": len(self._last_inference),
            "model_dir": self._config.model_dir,
            "stages_enabled": {
                "statistical": self._config.stages.statistical.enabled,
                "classification": self._config.stages.classification.enabled,
                "predictive": self._config.stages.predictive.enabled,
                "unknown_fault": self._config.stages.unknown_fault.enabled,
            },
        }
