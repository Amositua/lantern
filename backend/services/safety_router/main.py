from fastapi import FastAPI

from common.config import get_settings
from common.gcp_clients import get_genai_client
from common.health import run_checks
from common.logging_utils import get_logger

logger = get_logger("safety_router")
settings = get_settings()

app = FastAPI(title="Lantern Safety Router")


@app.get("/health")
def health() -> dict:
    return {"service": "safety_router", "status": "ok", "environment": settings.environment}


@app.get("/health/deep")
def health_deep() -> dict:
    checks = run_checks({"vertex_genai": get_genai_client})
    return {"service": "safety_router", "checks": checks}
