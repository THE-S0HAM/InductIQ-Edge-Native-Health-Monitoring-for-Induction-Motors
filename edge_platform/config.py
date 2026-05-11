"""
Platform configuration loader.
Reads YAML config with environment variable overrides.
"""

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


def get_project_root() -> Path:
    """Get the project root directory."""
    return Path(__file__).parent.parent.resolve()


def resolve_path(path_str: str) -> str:
    """Resolve a path relative to project root if not absolute."""
    p = Path(path_str)
    if p.is_absolute():
        return str(p)
    return str(get_project_root() / p)


def load_yaml_config(config_path: str | None = None) -> dict[str, Any]:
    """Load platform configuration from YAML file."""
    if config_path is None:
        config_path = os.environ.get(
            "EDGE_CONFIG_PATH",
            "config/platform.yaml"
        )
    
    path = Path(config_path)
    if not path.is_absolute() and not path.exists():
        # Try relative to project root
        path = get_project_root() / path
    
    if not path.exists():
        # Fallback to local config
        local = get_project_root() / "config" / "platform.yaml"
        if local.exists():
            path = local
        else:
            return {}
    
    with open(path, "r") as f:
        return yaml.safe_load(f) or {}


class MQTTConfig(BaseModel):
    broker_host: str = "localhost"
    broker_port: int = 1883
    keepalive: int = 60
    qos: int = 1
    topic_prefix: str = "iiot/site/SITE_001"
    reconnect_interval: int = 5
    max_reconnect_attempts: int = 0
    buffer_size: int = 1000


class SQLiteConfig(BaseModel):
    path: str = "/var/lib/edge-ai/hot.db"
    wal_mode: bool = True
    journal_size_limit: int = 67108864
    cache_size: int = -8000
    busy_timeout: int = 5000


class DuckDBConfig(BaseModel):
    path: str = "/var/lib/edge-ai/analytics.duckdb"
    memory_limit: str = "128MB"
    threads: int = 2


class ParquetConfig(BaseModel):
    archive_dir: str = "/var/lib/edge-ai/archives"
    compression: str = "snappy"
    row_group_size: int = 10000


class StorageConfig(BaseModel):
    sqlite: SQLiteConfig = SQLiteConfig()
    duckdb: DuckDBConfig = DuckDBConfig()
    parquet: ParquetConfig = ParquetConfig()


class RetentionConfig(BaseModel):
    hot_hours: int = 24
    warm_days: int = 7
    cold_days: int = 90
    archive_days: int = 365
    cleanup_interval_minutes: int = 60


class StatisticalStageConfig(BaseModel):
    enabled: bool = True
    z_score_threshold: float = 3.0
    ewma_alpha: float = 0.3
    window_size: int = 60


class ClassificationStageConfig(BaseModel):
    enabled: bool = True
    model_type: str = "lightgbm"
    model_file: str = "fault_classifier.pkl"


class PredictiveStageConfig(BaseModel):
    enabled: bool = True
    degradation_window_hours: int = 168
    rul_model_file: str = "rul_estimator.pkl"


class UnknownFaultStageConfig(BaseModel):
    enabled: bool = True
    isolation_contamination: float = 0.1
    min_cluster_samples: int = 5


class InferenceStagesConfig(BaseModel):
    statistical: StatisticalStageConfig = StatisticalStageConfig()
    classification: ClassificationStageConfig = ClassificationStageConfig()
    predictive: PredictiveStageConfig = PredictiveStageConfig()
    unknown_fault: UnknownFaultStageConfig = UnknownFaultStageConfig()


class InferenceConfig(BaseModel):
    enabled: bool = True
    model_dir: str = "/var/lib/edge-ai/models"
    batch_size: int = 10
    inference_interval_seconds: int = 30
    confidence_threshold: float = 0.7
    unknown_fault_threshold: float = 0.5
    max_concurrent_inferences: int = 2
    stages: InferenceStagesConfig = InferenceStagesConfig()


class AlertConfig(BaseModel):
    enabled: bool = True
    cooldown_seconds: int = 300
    dedup_window_seconds: int = 60
    escalation_delay_seconds: int = 900
    max_active_alerts: int = 100


class HealthConfig(BaseModel):
    monitor_interval_seconds: int = 30
    cpu_warning_percent: float = 80
    cpu_critical_percent: float = 95
    ram_warning_percent: float = 75
    ram_critical_percent: float = 90
    disk_warning_percent: float = 80
    disk_critical_percent: float = 95
    temperature_warning_celsius: float = 70
    temperature_critical_celsius: float = 80


class SensorConfig(BaseModel):
    sampling_interval_seconds: int = 5
    adaptive_sampling: bool = True
    min_interval_seconds: int = 1
    max_interval_seconds: int = 60
    buffer_size: int = 100


class APIConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8420
    workers: int = 2
    reload: bool = False
    api_key_enabled: bool = True
    rate_limit_per_minute: int = 120


class PlatformConfig(BaseModel):
    """Root configuration model for the entire platform."""
    name: str = "Industrial Edge AI"
    version: str = "1.0.0"
    site_id: str = "SITE_001"
    environment: str = "production"
    mqtt: MQTTConfig = MQTTConfig()
    api: APIConfig = APIConfig()
    storage: StorageConfig = StorageConfig()
    retention: RetentionConfig = RetentionConfig()
    inference: InferenceConfig = InferenceConfig()
    alerts: AlertConfig = AlertConfig()
    health: HealthConfig = HealthConfig()
    sensors: SensorConfig = SensorConfig()


def get_config(config_path: str | None = None) -> PlatformConfig:
    """Load and validate platform configuration."""
    # Load .env file if present
    env_file = get_project_root() / ".env"
    if env_file.exists():
        from dotenv import load_dotenv
        load_dotenv(env_file)
    
    raw = load_yaml_config(config_path)
    platform_data = raw.get("platform", {})
    
    # Merge top-level sections into platform data
    for key in ["mqtt", "api", "storage", "retention", "inference",
                "alerts", "health", "sensors"]:
        if key in raw:
            platform_data[key] = raw[key]
    
    # Apply environment variable overrides
    if site_id := os.environ.get("EDGE_SITE_ID"):
        platform_data["site_id"] = site_id
    if mqtt_host := os.environ.get("EDGE_MQTT_HOST"):
        platform_data.setdefault("mqtt", {})["broker_host"] = mqtt_host
    
    config = PlatformConfig(**platform_data)
    
    # Resolve relative paths to absolute
    config.storage.sqlite.path = resolve_path(config.storage.sqlite.path)
    config.storage.duckdb.path = resolve_path(config.storage.duckdb.path)
    config.storage.parquet.archive_dir = resolve_path(config.storage.parquet.archive_dir)
    config.inference.model_dir = resolve_path(config.inference.model_dir)
    
    return config
