from fastapi import FastAPI

from common.config import get_settings
from common.gcp_clients import get_pubsub_publisher
from common.health import run_checks
from common.logging_utils import get_logger

logger = get_logger("action")
settings = get_settings()

app = FastAPI(title="Lantern Action / Executor Agent")


@app.get("/health")
def health() -> dict:
    return {"service": "action", "status": "ok", "environment": settings.environment}


@app.get("/health/deep")
def health_deep() -> dict:
    checks = run_checks({"pubsub": get_pubsub_publisher})
    return {"service": "action", "checks": checks}
