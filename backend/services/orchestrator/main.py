import httpx
from fastapi import FastAPI

from common.config import get_settings
from common.gcp_clients import get_firestore_client, get_genai_client, get_pubsub_publisher
from common.health import run_checks
from common.logging_utils import get_logger

logger = get_logger("orchestrator")
settings = get_settings()

app = FastAPI(title="Lantern Orchestrator")

DOWNSTREAM_SERVICES = {
    "perception": settings.perception_url,
    "clarifier": settings.clarifier_url,
    "action": settings.action_url,
    "safety_router": settings.safety_router_url,
    "memory": settings.memory_url,
    "live_session_gateway": settings.live_session_gateway_url,
}


@app.get("/health")
def health() -> dict:
    return {"service": "orchestrator", "status": "ok", "environment": settings.environment}


@app.get("/health/deep")
def health_deep() -> dict:
    checks = run_checks(
        {
            "vertex_genai": get_genai_client,
            "firestore": get_firestore_client,
            "pubsub": get_pubsub_publisher,
            "adk_root_agent": _load_adk_agent,
        }
    )
    return {"service": "orchestrator", "checks": checks}


def _load_adk_agent():
    from .adk_agent import root_agent

    return root_agent


@app.get("/hello")
async def hello() -> dict:
    """Round-trips a hello through every downstream agent service.

    Confirms the orchestrator can reach the rest of the fleet over HTTP
    before any real routing logic is built on top of it.
    """
    results: dict = {}
    async with httpx.AsyncClient(timeout=3.0) as client:
        for name, base_url in DOWNSTREAM_SERVICES.items():
            try:
                resp = await client.get(f"{base_url}/health")
                resp.raise_for_status()
                results[name] = resp.json()
            except httpx.HTTPError as exc:
                logger.warning("hello: %s unreachable: %s", name, exc)
                results[name] = {"status": "unreachable", "detail": str(exc)}
    return {"from": "orchestrator", "message": "hello world", "downstream": results}
