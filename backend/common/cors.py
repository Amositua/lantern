"""CORS for the one origin that needs it: the dashboard, calling Memory
and Action directly from the browser."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings


def add_dashboard_cors(app: FastAPI) -> None:
    settings = get_settings()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.dashboard_origin],
        allow_methods=["GET", "POST", "PATCH", "PUT"],
        allow_headers=["Content-Type"],
    )
