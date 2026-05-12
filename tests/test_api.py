"""Tests for API endpoints."""

import pytest
from fastapi.testclient import TestClient

from edge_platform.api.app import create_app
from edge_platform.config import PlatformConfig


@pytest.fixture
def test_app():
    """Create a test FastAPI app."""
    config = PlatformConfig(
        name="Test Platform",
        site_id="TEST_SITE",
        environment="test",
    )
    return create_app(config, platform=None)


@pytest.fixture
def client(test_app):
    """Create a test client."""
    return TestClient(test_app)


def test_health_endpoint(client):
    """Test health check endpoint."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert data["status"] == "healthy"


def test_api_docs_endpoint(client):
    """Test API documentation endpoint."""
    response = client.get("/api/docs")
    assert response.status_code == 200


def test_dashboard_endpoint(client):
    """Test dashboard endpoint."""
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")


def test_api_key_required(client):
    """Test that API key is required for protected endpoints."""
    response = client.get("/api/v1/devices")
    # Should require API key
    assert response.status_code in [401, 403]


def test_api_key_accepted(client):
    """Test that valid API key is accepted."""
    headers = {"X-API-Key": "edgeai-prod-k8x2m9v4q7w1n6j3p5r0t8y"}
    response = client.get("/api/v1/devices", headers=headers)
    # Should not be 401/403 (might be 503 if platform not initialized)
    assert response.status_code != 401
