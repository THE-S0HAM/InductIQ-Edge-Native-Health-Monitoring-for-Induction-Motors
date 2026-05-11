"""Inference API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from typing import Any

router = APIRouter()


@router.get("/inference/{device_id}")
async def get_latest_inference(
    request: Request,
    device_id: str,
) -> dict[str, Any]:
    """Get the latest inference result for a device."""
    platform = request.app.state.platform
    if not platform:
        raise HTTPException(503, "Platform not initialized")
    
    result = await platform.storage.get_latest_inference(device_id)
    if not result:
        raise HTTPException(404, f"No inference data for device {device_id}")
    return result


@router.get("/inference/{device_id}/degradation")
async def get_degradation_summary(
    request: Request,
    device_id: str,
) -> dict[str, Any]:
    """Get degradation analysis for a device."""
    platform = request.app.state.platform
    if not platform:
        raise HTTPException(503, "Platform not initialized")
    
    summary = platform.inference_pipeline._predictive.get_device_summary(device_id)
    return {"device_id": device_id, **summary}


@router.get("/inference/pipeline/stats")
async def get_pipeline_stats(request: Request) -> dict[str, Any]:
    """Get AI pipeline statistics."""
    platform = request.app.state.platform
    if not platform:
        raise HTTPException(503, "Platform not initialized")
    
    return platform.inference_pipeline.get_stats()
