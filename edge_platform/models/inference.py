"""
AI inference result models.
Supports multi-stage inference pipeline outputs.
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class FaultClass(str, Enum):
    """Industrial fault taxonomy."""
    BEARING_WEAR = "bearing_wear"
    ROTOR_IMBALANCE = "rotor_imbalance"
    SHAFT_MISALIGNMENT = "shaft_misalignment"
    MOISTURE_INGRESS = "moisture_ingress"
    OVERHEATING = "overheating"
    CAVITATION = "cavitation"
    LUBRICATION_FAILURE = "lubrication_failure"
    ROTOR_BAR_DAMAGE = "rotor_bar_damage"
    ELECTRICAL_ARCING = "electrical_arcing"
    LOOSE_MOUNTING = "loose_mounting"
    INSULATION_BREAKDOWN = "insulation_breakdown"
    UNKNOWN_FAULT = "unknown_fault"
    EMERGING_PATTERN = "emerging_pattern"
    NORMAL = "normal"


class HealthScores(BaseModel):
    """Component health scores (0-100, higher is healthier)."""
    overall: float = 100.0
    thermal: float = 100.0
    vibration: float = 100.0
    electrical: float = 100.0
    smoke: float = 100.0
    acoustic: float = 100.0


class InferenceResult(BaseModel):
    """Complete inference result from the AI pipeline."""
    timestamp: int = Field(default_factory=lambda: int(time.time()))
    device_id: str
    
    # Classification
    fault_class: FaultClass = FaultClass.NORMAL
    confidence: float = 1.0
    secondary_faults: list[dict[str, float]] = Field(default_factory=list)
    
    # Health scores
    health_scores: HealthScores = Field(default_factory=HealthScores)
    
    # Predictive
    rul_hours: float | None = None
    degradation_rate: float | None = None
    trend_direction: str | None = None  # "improving", "stable", "degrading"
    
    # Root cause
    root_cause: str | None = None
    contributing_factors: list[str] = Field(default_factory=list)
    
    # Metadata
    model_version: str = "1.0.0"
    inference_stage: str = "statistical"  # statistical, classification, predictive, unknown
    processing_time_ms: float | None = None
    
    def is_anomaly(self) -> bool:
        """Check if this result indicates an anomaly."""
        return self.fault_class != FaultClass.NORMAL
    
    def severity_level(self) -> str:
        """Determine severity based on health and confidence."""
        if self.health_scores.overall < 30:
            return "CRITICAL"
        elif self.health_scores.overall < 50:
            return "HIGH"
        elif self.health_scores.overall < 70:
            return "WARNING"
        return "INFO"


class StatisticalResult(BaseModel):
    """Stage 1: Statistical anomaly detection result."""
    is_anomaly: bool = False
    anomaly_scores: dict[str, float] = Field(default_factory=dict)
    z_scores: dict[str, float] = Field(default_factory=dict)
    threshold_violations: list[str] = Field(default_factory=list)


class ClassificationResult(BaseModel):
    """Stage 2: Fault classification result."""
    fault_class: FaultClass = FaultClass.NORMAL
    confidence: float = 1.0
    class_probabilities: dict[str, float] = Field(default_factory=dict)


class PredictiveResult(BaseModel):
    """Stage 3: Predictive maintenance result."""
    rul_hours: float | None = None
    degradation_rate: float = 0.0
    trend_direction: str = "stable"
    time_to_warning: float | None = None
    time_to_critical: float | None = None


class UnknownFaultResult(BaseModel):
    """Stage 4: Unknown fault analysis result."""
    is_unknown: bool = False
    nearest_known_fault: FaultClass | None = None
    nearest_distance: float | None = None
    cluster_id: int | None = None
    anomaly_score: float = 0.0
