"""
API security - API key authentication and rate limiting.
"""

from __future__ import annotations

import hashlib
import os
import time
from collections import defaultdict

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

# API key from environment
API_KEY = os.environ.get("EDGE_API_KEY", "change-me-in-env")
API_KEY_HASH = os.environ.get("EDGE_API_KEY_HASH", "")

# Rate limiting state
_rate_limits: dict[str, list[float]] = defaultdict(list)
_RATE_LIMIT_WINDOW = 60  # seconds
_RATE_LIMIT_MAX = 120  # requests per window

# Paths that don't require auth
PUBLIC_PATHS = {"/health", "/api/docs", "/openapi.json", "/", "/dashboard", "/favicon.ico"}


async def api_key_middleware(request: Request, call_next):
    """Validate API key for protected endpoints."""
    path = request.url.path
    
    # Skip auth for CORS preflight
    if request.method == "OPTIONS":
        return await call_next(request)
    
    # Skip auth for public paths, dashboard, and static files
    if any(path.startswith(p) for p in PUBLIC_PATHS) or path.startswith("/static"):
        return await call_next(request)
    
    # Skip auth for dashboard sub-routes
    if path.startswith("/dashboard"):
        return await call_next(request)
    
    # Skip auth for WebSocket (handled separately)
    if path.startswith("/ws"):
        return await call_next(request)
    
    # Check API key
    api_key = request.headers.get("X-API-Key") or request.query_params.get("api_key")
    
    if not api_key:
        return JSONResponse(
            status_code=401,
            content={"detail": "API key required"},
        )
    
    if not _verify_key(api_key):
        return JSONResponse(
            status_code=403,
            content={"detail": "Invalid API key"},
        )
    
    # Rate limiting
    client_ip = request.client.host if request.client else "unknown"
    if not _check_rate_limit(client_ip):
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded"},
        )
    
    return await call_next(request)


def _verify_key(key: str) -> bool:
    """Verify an API key."""
    if API_KEY_HASH:
        key_hash = hashlib.sha256(key.encode()).hexdigest()
        return key_hash == API_KEY_HASH
    # Fallback to direct comparison (dev mode)
    return key == API_KEY


def _check_rate_limit(client_id: str) -> bool:
    """Check if client is within rate limits."""
    now = time.time()
    window_start = now - _RATE_LIMIT_WINDOW
    
    # Clean old entries
    _rate_limits[client_id] = [
        t for t in _rate_limits[client_id] if t > window_start
    ]
    
    if len(_rate_limits[client_id]) >= _RATE_LIMIT_MAX:
        return False
    
    _rate_limits[client_id].append(now)
    return True
