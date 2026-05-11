"""
Dashboard route - serves the static HTML dashboard.
All data is fetched client-side via WebSocket and REST API.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter()

# Read dashboard HTML once at import time
_DASHBOARD_HTML = (
    Path(__file__).parent.parent / "templates" / "dashboard.html"
).read_text(encoding="utf-8")


@router.get("/", response_class=HTMLResponse)
@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_home(request: Request):
    """Serve the main dashboard page."""
    return HTMLResponse(content=_DASHBOARD_HTML)
