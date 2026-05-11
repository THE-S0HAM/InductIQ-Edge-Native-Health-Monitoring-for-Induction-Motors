"""
FastAPI application factory.
Creates the main API application with all routes and middleware.
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from edge_platform.api.routes import alerts, dashboard, devices, health, inference, telemetry, websocket, cloud
from edge_platform.api.security import api_key_middleware
from edge_platform.config import PlatformConfig

logger = logging.getLogger(__name__)


def create_app(config: PlatformConfig, platform: Any = None) -> FastAPI:
    """
    Create and configure the FastAPI application.
    
    Args:
        config: Platform configuration
        platform: Platform instance (injected for dependency access)
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Application lifespan - startup and shutdown."""
        logger.info("API server starting...")
        yield
        logger.info("API server shutting down...")

    app = FastAPI(
        title="Industrial Edge AI Platform",
        description="Edge-native predictive maintenance API",
        version=config.version,
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,  # Save memory
    )

    # Store platform reference for dependency injection
    app.state.platform = platform
    app.state.config = config

    # CORS — allow all origins (needed for accessing Pi dashboard from any device)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Process-Time"],
    )

    # API key middleware
    if config.api.api_key_enabled:
        app.middleware("http")(api_key_middleware)

    # Request timing middleware
    @app.middleware("http")
    async def timing_middleware(request: Request, call_next):
        start = time.time()
        response = await call_next(request)
        duration = time.time() - start
        response.headers["X-Process-Time"] = f"{duration:.4f}"
        return response

    # Mount routes
    app.include_router(telemetry.router, prefix="/api/v1", tags=["telemetry"])
    app.include_router(inference.router, prefix="/api/v1", tags=["inference"])
    app.include_router(alerts.router, prefix="/api/v1", tags=["alerts"])
    app.include_router(devices.router, prefix="/api/v1", tags=["devices"])
    app.include_router(health.router, prefix="/api/v1", tags=["health"])
    app.include_router(cloud.router, prefix="/api/v1", tags=["cloud"])
    app.include_router(websocket.router, prefix="/ws", tags=["websocket"])
    app.include_router(dashboard.router, tags=["dashboard"])

    # Root health check
    @app.get("/health", tags=["system"])
    async def root_health():
        return {
            "status": "healthy",
            "platform": config.name,
            "version": config.version,
            "uptime": time.time(),
        }

    # Favicon — inline SVG to avoid 404
    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
            '<rect width="32" height="32" rx="6" fill="#6366f1"/>'
            '<text x="16" y="24" font-size="20" text-anchor="middle" fill="white">⚡</text>'
            '</svg>'
        )
        return Response(content=svg, media_type="image/svg+xml")

    return app
