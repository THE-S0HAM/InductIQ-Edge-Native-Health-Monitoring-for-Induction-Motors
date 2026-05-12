"""Tests for configuration loading."""

import os
import tempfile
from pathlib import Path

import pytest
import yaml

from edge_platform.config import get_config, load_yaml_config, resolve_path


def test_resolve_path_absolute():
    """Test resolving absolute paths."""
    abs_path = "/var/lib/edge-ai/data.db"
    resolved = resolve_path(abs_path)
    assert resolved == abs_path


def test_resolve_path_relative():
    """Test resolving relative paths."""
    rel_path = "data/hot.db"
    resolved = resolve_path(rel_path)
    assert "data/hot.db" in resolved
    assert Path(resolved).is_absolute()


def test_load_yaml_config():
    """Test YAML config loading."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_file = Path(tmpdir) / "test.yaml"
        config_data = {
            "platform": {
                "name": "Test",
                "version": "1.0.0",
                "site_id": "TEST",
            }
        }
        
        with open(config_file, "w") as f:
            yaml.dump(config_data, f)
        
        loaded = load_yaml_config(str(config_file))
        assert loaded["platform"]["name"] == "Test"


def test_get_config_defaults():
    """Test config loading with defaults."""
    config = get_config()
    
    assert config.name == "Industrial Edge AI"
    assert config.version == "1.0.0"
    assert config.site_id == "SITE_001"
    assert config.api.port == 8420
    assert config.mqtt.broker_host == "localhost"


def test_get_config_env_override():
    """Test environment variable overrides."""
    os.environ["EDGE_SITE_ID"] = "CUSTOM_SITE"
    
    try:
        config = get_config()
        assert config.site_id == "CUSTOM_SITE"
    finally:
        del os.environ["EDGE_SITE_ID"]


def test_config_path_resolution():
    """Test that config paths are resolved to absolute."""
    config = get_config()
    
    # Paths should be absolute after resolution
    assert Path(config.storage.sqlite.path).is_absolute()
    assert Path(config.storage.parquet.archive_dir).is_absolute()
    assert Path(config.inference.model_dir).is_absolute()
