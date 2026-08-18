from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from common.config import get_settings
from common.logging_utils import get_logger
from common.memory_client import MemoryAgentError

from . import safety_router
from .schemas import SafetyCheckRequest, SafetyCheckResult

logger = get_logger("safety_router")
settings = get_settings()

app = FastAPI(title="Lantern Safety Router")


@app.exception_handler(MemoryAgentError)
async def _handle_memory_agent_error(request: Request, exc: MemoryAgentError):
    return JSONResponse(status_code=status.HTTP_502_BAD_GATEWAY, content={"detail": str(exc)})


@app.get("/health")
def health() -> dict:
    return {"service": "safety_router", "status": "ok", "environment": settings.environment}


@app.get("/health/deep")
def health_deep() -> dict:
    # Deliberately no Gemini dependency here -- crisis detection has to work
    # even if Vertex AI is unreachable, so it stays a fixed, fast, local check.
    return {"service": "safety_router", "checks": {}}


@app.post("/safety/check")
def check_turn(payload: SafetyCheckRequest) -> SafetyCheckResult:
    """Runs on every turn. A crisis phrase or confidence below the safety
    threshold halts and hands off; if case_id points at a still-proposed
    case, it's vetoed on the spot."""
    return safety_router.check_turn(payload)
