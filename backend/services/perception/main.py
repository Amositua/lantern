from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from common.config import get_settings
from common.gcp_clients import ClientInitError, get_genai_client
from common.health import run_checks
from common.logging_utils import get_logger
from common.memory_client import MemoryAgentError

from . import perception
from .schemas import PerceptionRequest, PerceptionResult

logger = get_logger("perception")
settings = get_settings()

app = FastAPI(title="Lantern Perception Agent")


@app.exception_handler(MemoryAgentError)
async def _handle_memory_agent_error(request: Request, exc: MemoryAgentError):
    return JSONResponse(status_code=status.HTTP_502_BAD_GATEWAY, content={"detail": str(exc)})


@app.exception_handler(ClientInitError)
async def _handle_client_init_error(request: Request, exc: ClientInitError):
    return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"detail": str(exc)})


@app.get("/health")
def health() -> dict:
    return {"service": "perception", "status": "ok", "environment": settings.environment}


@app.get("/health/deep")
def health_deep() -> dict:
    checks = run_checks({"vertex_genai": get_genai_client})
    return {"service": "perception", "checks": checks}


@app.post("/perceive")
def perceive(payload: PerceptionRequest) -> PerceptionResult:
    """Matches a camera frame against this user's known meds. Never returns
    a drug identity that isn't already in their Life Graph."""
    return perception.perceive(payload)
