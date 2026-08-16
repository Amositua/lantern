from fastapi import FastAPI

from common.config import get_settings
from common.gcp_clients import get_cloud_sql_engine, get_firestore_client
from common.health import run_checks
from common.logging_utils import get_logger

logger = get_logger("memory")
settings = get_settings()

app = FastAPI(title="Lantern Memory Agent")


@app.get("/health")
def health() -> dict:
    return {"service": "memory", "status": "ok", "environment": settings.environment}


@app.get("/health/deep")
def health_deep() -> dict:
    checks = run_checks(
        {
            "firestore": get_firestore_client,
            "cloud_sql_pgvector": get_cloud_sql_engine,
        }
    )
    return {"service": "memory", "checks": checks}
