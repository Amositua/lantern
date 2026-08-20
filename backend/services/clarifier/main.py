from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from common.config import get_settings
from common.gcp_clients import get_genai_client
from common.health import run_checks
from common.logging_utils import get_logger
from common.memory_client import MemoryAgentError

from . import clarifier
from .schemas import (
    ClarifyingQuestion,
    DocumentAnswer,
    DocumentQuestionRequest,
    MedicationQuestionRequest,
    PreferenceCorrectionRequest,
    PreferenceCorrectionResult,
    ResolutionQuestionRequest,
    ResolveContradictionRequest,
)

logger = get_logger("clarifier")
settings = get_settings()

app = FastAPI(title="Lantern Clarifier / Dialogue Agent")


@app.exception_handler(MemoryAgentError)
async def _handle_memory_agent_error(request: Request, exc: MemoryAgentError):
    return JSONResponse(status_code=status.HTTP_502_BAD_GATEWAY, content={"detail": str(exc)})


@app.get("/health")
def health() -> dict:
    return {"service": "clarifier", "status": "ok", "environment": settings.environment}


@app.get("/health/deep")
def health_deep() -> dict:
    checks = run_checks({"vertex_genai": get_genai_client})
    return {"service": "clarifier", "checks": checks}


@app.post("/clarify/medication-question")
def medication_question(payload: MedicationQuestionRequest) -> ClarifyingQuestion:
    """The distinguishing question for a look-alike match from Perception."""
    return clarifier.ask_medication_distinguishing_question(payload)


@app.post("/clarify/preference-correction")
def preference_correction(payload: PreferenceCorrectionRequest) -> PreferenceCorrectionResult:
    """Classifies a correction as one-off or durable, asking rather than
    guessing when the utterance doesn't already make it clear. Pass
    is_override explicitly to resume after the user answers that question."""
    return clarifier.resolve_preference_correction(payload)


@app.post("/clarify/resolution-question")
def resolution_question(payload: ResolutionQuestionRequest) -> ClarifyingQuestion:
    """The question for a preference that contradicts an already-hardened one."""
    return clarifier.ask_resolution_question(payload)


@app.post("/clarify/resolution-question/resolve")
def resolve_contradiction(payload: ResolveContradictionRequest) -> dict:
    return clarifier.resolve_contradiction(payload)


@app.post("/clarify/document-question")
def document_question(payload: DocumentQuestionRequest) -> DocumentAnswer:
    """Answers grounded only in the user's own enrolled letters/labels --
    says so plainly rather than guessing when nothing on file answers it."""
    return clarifier.answer_document_question(payload)
