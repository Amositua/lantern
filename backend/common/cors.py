"""CORS for the dashboard, calling Memory and Action directly from the
browser. Cloud Run actually serves one deployed service under two valid
hostnames -- a project-number-qualified one and a hash-based one -- so
DASHBOARD_ORIGIN can be a comma-separated list rather than forcing a
single choice of which URL "is" the dashboard.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings


def add_dashboard_cors(app: FastAPI) -> None:
    settings = get_settings()
    origins = [origin.strip() for origin in settings.dashboard_origin.split(",") if origin.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["GET", "POST", "PATCH", "PUT"],
        allow_headers=["Content-Type"],
    )
