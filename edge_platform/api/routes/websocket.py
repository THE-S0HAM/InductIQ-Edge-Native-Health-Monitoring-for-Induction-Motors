"""WebSocket endpoints for real-time telemetry streaming."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

import orjson

logger = logging.getLogger(__name__)

router = APIRouter()

# Active WebSocket connections
_connections: set[WebSocket] = set()

# Throttle: max 1 broadcast per second per type
_last_broadcast: dict[str, float] = {}
_BROADCAST_INTERVAL = 1.0  # seconds


@router.websocket("/telemetry")
async def telemetry_stream(websocket: WebSocket):
    """
    WebSocket endpoint for live telemetry streaming.
    Clients receive real-time telemetry and inference updates.
    """
    await websocket.accept()
    _connections.add(websocket)
    logger.info("WebSocket client connected (total: %d)", len(_connections))
    
    try:
        while True:
            # Keep connection alive, handle client messages
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30)
                # Client can send subscription preferences
                # e.g., {"subscribe": ["MOTOR_001", "MOTOR_002"]}
            except asyncio.TimeoutError:
                # Send heartbeat
                await websocket.send_json({"type": "heartbeat", "timestamp": int(time.time())})
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.debug("WebSocket error: %s", e)
    finally:
        _connections.discard(websocket)
        logger.info("WebSocket client disconnected (total: %d)", len(_connections))


async def broadcast_telemetry(data: dict[str, Any]) -> None:
    """Broadcast telemetry data to all connected WebSocket clients. Throttled to 1Hz."""
    if not _connections:
        return
    
    now = time.time()
    if (now - _last_broadcast.get("telemetry", 0)) < _BROADCAST_INTERVAL:
        return  # Skip — throttled
    _last_broadcast["telemetry"] = now
    
    message = orjson.dumps({"type": "telemetry", "data": data}).decode()
    
    disconnected = set()
    for ws in _connections:
        try:
            await ws.send_text(message)
        except Exception:
            disconnected.add(ws)
    
    _connections.difference_update(disconnected)


async def broadcast_alert(alert: dict[str, Any]) -> None:
    """Broadcast alert to all connected WebSocket clients. Always sent immediately."""
    if not _connections:
        return
    
    message = orjson.dumps({"type": "alert", "data": alert}).decode()
    
    disconnected = set()
    for ws in _connections:
        try:
            await ws.send_text(message)
        except Exception:
            disconnected.add(ws)
    
    _connections.difference_update(disconnected)


async def broadcast_inference(result: dict[str, Any]) -> None:
    """Broadcast inference result to all connected WebSocket clients. Throttled to 1Hz."""
    if not _connections:
        return
    
    now = time.time()
    if (now - _last_broadcast.get("inference", 0)) < _BROADCAST_INTERVAL:
        return
    _last_broadcast["inference"] = now
    
    message = orjson.dumps({"type": "inference", "data": result}).decode()
    
    disconnected = set()
    for ws in _connections:
        try:
            await ws.send_text(message)
        except Exception:
            disconnected.add(ws)
    
    _connections.difference_update(disconnected)
