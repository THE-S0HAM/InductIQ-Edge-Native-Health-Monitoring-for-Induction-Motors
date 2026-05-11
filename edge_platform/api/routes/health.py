"""Health and system status API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from typing import Any

router = APIRouter()


@router.get("/health/edge")
async def get_edge_health(request: Request) -> dict[str, Any]:
    """Get edge device (Raspberry Pi) health metrics."""
    platform = request.app.state.platform
    if not platform:
        raise HTTPException(503, "Platform not initialized")
    
    return platform.health_monitor.get_health_dict()


@router.get("/health/platform")
async def get_platform_health(request: Request) -> dict[str, Any]:
    """Get overall platform health and component status."""
    platform = request.app.state.platform
    if not platform:
        raise HTTPException(503, "Platform not initialized")
    
    return {
        "status": "healthy",
        "components": {
            "mqtt": platform.mqtt_client.get_stats(),
            "stream": platform.stream_processor.get_stats(),
            "inference": platform.inference_pipeline.get_stats(),
            "alerts": platform.alert_engine.get_stats(),
            "storage": await platform.storage.get_table_counts(),
        },
    }


@router.get("/health/storage")
async def get_storage_health(request: Request) -> dict[str, Any]:
    """Get storage statistics."""
    platform = request.app.state.platform
    if not platform:
        raise HTTPException(503, "Platform not initialized")
    
    counts = await platform.storage.get_table_counts()
    archive_stats = await platform.archiver.get_archive_stats()
    
    return {
        "hot_storage": counts,
        "cold_storage": archive_stats,
    }
