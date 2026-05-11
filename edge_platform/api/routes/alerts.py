"""Alert API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from typing import Any

router = APIRouter()


@router.get("/alerts")
async def get_active_alerts(
    request: Request,
    severity: str | None = Query(default=None),
    limit: int = Query(default=50, le=200),
) -> dict[str, Any]:
    """Get active alerts."""
    platform = request.app.state.platform
    if not platform:
        raise HTTPException(503, "Platform not initialized")
    
    alerts = await platform.storage.get_active_alerts(severity, limit)
    return {"count": len(alerts), "alerts": alerts}


@router.get("/alerts/counts")
async def get_alert_counts(request: Request) -> dict[str, int]:
    """Get alert counts by severity."""
    platform = request.app.state.platform
    if not platform:
        raise HTTPException(503, "Platform not initialized")
    
    return platform.alert_engine.get_alert_counts()


@router.post("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(request: Request, alert_id: str) -> dict[str, Any]:
    """Acknowledge an alert."""
    platform = request.app.state.platform
    if not platform:
        raise HTTPException(503, "Platform not initialized")
    
    success = await platform.alert_engine.acknowledge(alert_id)
    if not success:
        raise HTTPException(404, f"Alert {alert_id} not found")
    
    await platform.storage.acknowledge_alert(alert_id)
    return {"status": "acknowledged", "alert_id": alert_id}


@router.post("/alerts/{alert_id}/resolve")
async def resolve_alert(request: Request, alert_id: str) -> dict[str, Any]:
    """Resolve an alert."""
    platform = request.app.state.platform
    if not platform:
        raise HTTPException(503, "Platform not initialized")
    
    success = await platform.alert_engine.resolve(alert_id)
    if not success:
        raise HTTPException(404, f"Alert {alert_id} not found")
    
    await platform.storage.resolve_alert(alert_id)
    return {"status": "resolved", "alert_id": alert_id}
