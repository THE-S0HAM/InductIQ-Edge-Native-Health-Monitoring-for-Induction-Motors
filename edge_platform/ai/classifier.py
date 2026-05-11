"""
Stage 2: ML-based fault classification.
Uses pre-trained models (RandomForest/LightGBM/ONNX) for fault type identification.
Training happens externally; only inference runs on the Raspberry Pi.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import numpy as np

from edge_platform.config import InferenceConfig
from edge_platform.models.inference import ClassificationResult, FaultClass

logger = logging.getLogger(__name__)

# Feature columns expected by the model (must match training)
EXPECTED_FEATURES = [
    "temperature_mean", "temperature_std", "temperature_latest", "temperature_rate_of_change",
    "humidity_mean", "humidity_std", "humidity_latest",
    "current_mean", "current_std", "current_latest", "current_rate_of_change",
    "vibration_x_mean", "vibration_x_std",
    "vibration_y_mean", "vibration_y_std",
    "vibration_z_mean", "vibration_z_std",
    "vibration_magnitude_mean", "vibration_magnitude_std", "vibration_magnitude_max",
    "vibration_rms", "vibration_peak_to_peak",
    "current_rms", "thermal_electrical_correlation",
]

# Fault class mapping (index → FaultClass)
FAULT_CLASS_MAP = {
    0: FaultClass.NORMAL,
    1: FaultClass.BEARING_WEAR,
    2: FaultClass.ROTOR_IMBALANCE,
    3: FaultClass.SHAFT_MISALIGNMENT,
    4: FaultClass.MOISTURE_INGRESS,
    5: FaultClass.OVERHEATING,
    6: FaultClass.CAVITATION,
    7: FaultClass.LUBRICATION_FAILURE,
    8: FaultClass.ROTOR_BAR_DAMAGE,
    9: FaultClass.ELECTRICAL_ARCING,
    10: FaultClass.LOOSE_MOUNTING,
    11: FaultClass.INSULATION_BREAKDOWN,
    12: FaultClass.UNKNOWN_FAULT,
    13: FaultClass.EMERGING_PATTERN,
}


class FaultClassifier:
    """
    ML fault classifier using pre-trained models.
    
    Supports:
    - scikit-learn RandomForest (joblib serialized)
    - LightGBM (native format)
    - ONNX Runtime (cross-platform optimized)
    
    Falls back to rule-based classification if no model is available.
    """

    def __init__(self, config: InferenceConfig):
        self._config = config
        self._model: Any = None
        self._model_type = config.stages.classification.model_type
        self._model_loaded = False

    async def load_model(self) -> None:
        """Load the pre-trained classification model."""
        model_dir = Path(self._config.model_dir)
        model_file = model_dir / self._config.stages.classification.model_file
        
        if not model_file.exists():
            logger.warning(
                "Classification model not found at %s, using rule-based fallback",
                model_file,
            )
            return
        
        try:
            # Load in executor to avoid blocking
            loop = asyncio.get_event_loop()
            
            if self._model_type == "lightgbm":
                import lightgbm as lgb
                self._model = await loop.run_in_executor(
                    None, lgb.Booster, {"model_file": str(model_file)}
                )
            elif self._model_type == "randomforest":
                import joblib
                self._model = await loop.run_in_executor(
                    None, joblib.load, str(model_file)
                )
            elif self._model_type == "onnx":
                import onnxruntime as ort
                self._model = await loop.run_in_executor(
                    None, ort.InferenceSession, str(model_file)
                )
            
            self._model_loaded = True
            logger.info("Loaded %s model from %s", self._model_type, model_file)
            
        except Exception as e:
            logger.error("Failed to load classification model: %s", e)
            self._model_loaded = False

    async def classify(self, features: dict[str, Any]) -> ClassificationResult:
        """
        Classify the fault type from extracted features.
        
        Args:
            features: Feature dictionary from FeatureExtractor
            
        Returns:
            ClassificationResult with fault class and confidence
        """
        if not self._model_loaded:
            return self._rule_based_classify(features)
        
        try:
            # Prepare feature vector
            feature_vector = self._prepare_features(features)
            
            # Run inference in executor (avoid blocking event loop)
            loop = asyncio.get_event_loop()
            
            if self._model_type == "lightgbm":
                probabilities = await loop.run_in_executor(
                    None, self._model.predict, feature_vector.reshape(1, -1)
                )
                probabilities = probabilities[0]
            elif self._model_type == "randomforest":
                probabilities = await loop.run_in_executor(
                    None, self._model.predict_proba, feature_vector.reshape(1, -1)
                )
                probabilities = probabilities[0]
            elif self._model_type == "onnx":
                input_name = self._model.get_inputs()[0].name
                result = await loop.run_in_executor(
                    None,
                    lambda: self._model.run(
                        None, {input_name: feature_vector.reshape(1, -1).astype(np.float32)}
                    ),
                )
                probabilities = result[1][0]  # Probabilities from ONNX
            else:
                return self._rule_based_classify(features)
            
            # Get top prediction
            predicted_idx = int(np.argmax(probabilities))
            confidence = float(probabilities[predicted_idx])
            
            fault_class = FAULT_CLASS_MAP.get(predicted_idx, FaultClass.UNKNOWN_FAULT)
            
            # Build class probabilities dict
            class_probs = {
                FAULT_CLASS_MAP.get(i, FaultClass.UNKNOWN_FAULT).value: float(p)
                for i, p in enumerate(probabilities)
            }
            
            return ClassificationResult(
                fault_class=fault_class,
                confidence=confidence,
                class_probabilities=class_probs,
            )
            
        except Exception as e:
            logger.error("Classification inference failed: %s", e)
            return self._rule_based_classify(features)

    def _prepare_features(self, features: dict[str, Any]) -> np.ndarray:
        """Prepare feature vector in the order expected by the model."""
        vector = []
        for col in EXPECTED_FEATURES:
            vector.append(features.get(col, 0.0))
        return np.array(vector, dtype=np.float64)

    def _rule_based_classify(self, features: dict[str, Any]) -> ClassificationResult:
        """
        Rule-based fallback classification when no ML model is available.
        Uses domain knowledge thresholds for basic fault detection.
        """
        fault_class = FaultClass.NORMAL
        confidence = 0.6  # Lower confidence for rule-based
        
        temp_latest = features.get("temperature_latest", 0)
        temp_rate = features.get("temperature_rate_of_change", 0)
        vib_mag = features.get("vibration_magnitude_mean", 0)
        vib_std = features.get("vibration_magnitude_std", 0)
        current_latest = features.get("current_latest", 0)
        current_std = features.get("current_std", 0)
        
        # Overheating detection
        if temp_latest > 85 or temp_rate > 1.0:
            fault_class = FaultClass.OVERHEATING
            confidence = min(0.5 + (temp_latest - 70) / 60, 0.9)
        
        # Bearing wear (high vibration with specific pattern)
        elif vib_mag > 5.0 and vib_std > 2.0:
            fault_class = FaultClass.BEARING_WEAR
            confidence = min(0.5 + vib_mag / 20, 0.85)
        
        # Rotor imbalance (periodic vibration)
        elif vib_mag > 3.0 and vib_std < 1.0:
            fault_class = FaultClass.ROTOR_IMBALANCE
            confidence = 0.65
        
        # Electrical issues
        elif current_std > 2.0 or current_latest > 10:
            fault_class = FaultClass.ELECTRICAL_ARCING
            confidence = min(0.5 + current_std / 5, 0.8)
        
        # Shaft misalignment (vibration + temperature)
        elif vib_mag > 3.5 and temp_latest > 70:
            fault_class = FaultClass.SHAFT_MISALIGNMENT
            confidence = 0.6
        
        return ClassificationResult(
            fault_class=fault_class,
            confidence=confidence,
            class_probabilities={fault_class.value: confidence},
        )
