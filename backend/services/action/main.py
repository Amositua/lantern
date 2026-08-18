import base64
import json
from datetime import datetime, timezone

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from common.config import get_settings
from common.gcp_clients import ClientInitError, get_genai_client, get_pubsub_publisher
from common.health import run_checks
from common.logging_utils import get_logger
from common.memory_client import MemoryAgentError

from . import enrollment, reengagement, reorder
from .reengagement_schemas import ReengagementFireRequest, ReengagementResult
from .reorder_schemas import ReorderConfirmRequest, ReorderProposal, ReorderProposeRequest, ReorderResult
from .schemas import (
    MedicationExtractRequest,
    MedicationExtractResponse,
    MedicationImportRequest,
    MedicationVerifyRequest,
    PaymentEnrollRequest,
)

logger = get_logger("action")
settings = get_settings()

app = FastAPI(title="Lantern Action / Executor Agent")


@app.exception_handler(enrollment.TrustedCircleNotVerified)
async def _handle_trusted_circle_not_verified(request: Request, exc: enrollment.TrustedCircleNotVerified):
    return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content={"detail": str(exc)})


@app.exception_handler(enrollment.EnrollmentError)
async def _handle_enrollment_error(request: Request, exc: enrollment.EnrollmentError):
    return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content={"detail": str(exc)})


@app.exception_handler(reorder.DuplicateOrderError)
async def _handle_duplicate_order(request: Request, exc: reorder.DuplicateOrderError):
    return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"detail": str(exc)})


@app.exception_handler(reorder.ReorderError)
async def _handle_reorder_error(request: Request, exc: reorder.ReorderError):
    return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content={"detail": str(exc)})


@app.exception_handler(MemoryAgentError)
async def _handle_memory_agent_error(request: Request, exc: MemoryAgentError):
    return JSONResponse(status_code=status.HTTP_502_BAD_GATEWAY, content={"detail": str(exc)})


@app.exception_handler(ClientInitError)
async def _handle_client_init_error(request: Request, exc: ClientInitError):
    return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"detail": str(exc)})


@app.get("/health")
def health() -> dict:
    return {"service": "action", "status": "ok", "environment": settings.environment}


@app.get("/health/deep")
def health_deep() -> dict:
    checks = run_checks({"vertex_genai": get_genai_client, "pubsub": get_pubsub_publisher})
    return {"service": "action", "checks": checks}


# ------------------------------------------------ medication enrollment --


@app.post("/enrollment/medications/prescription/extract")
def extract_prescription(payload: MedicationExtractRequest) -> MedicationExtractResponse:
    """Proposes fields from a prescription image. Writes nothing to the
    Life Graph — the caller must review these and call /verify to enroll."""
    return enrollment.extract_prescription(payload)


@app.post("/enrollment/medications/prescription/verify", status_code=status.HTTP_201_CREATED)
def verify_prescription(payload: MedicationVerifyRequest) -> dict:
    """Enrolls a medication once a human has confirmed the extracted (or
    manually entered) fields, carrying the verification evidence."""
    return enrollment.verify_and_enroll_medication(payload)


@app.post("/enrollment/medications/import-dispensing-record", status_code=status.HTTP_201_CREATED)
def import_dispensing_record(payload: MedicationImportRequest) -> dict:
    """Enrolls a medication straight from the pharmacy's own verified
    dispensing record — no separate human confirmation step needed."""
    return enrollment.import_medication_from_dispensing_record(payload)


# ---------------------------------------------------- payment enrollment --


@app.post("/enrollment/payment", status_code=status.HTTP_201_CREATED)
def enroll_payment(payload: PaymentEnrollRequest) -> dict:
    """Verifies a Paystack transaction server-side and stores only the
    resulting authorization_code — never the card itself."""
    return enrollment.enroll_payment(payload)


# --------------------------------------------------------- medication reorder --


@app.post("/reorder/propose")
def propose_reorder(payload: ReorderProposeRequest) -> ReorderProposal:
    """Reads back identity + amount + payee + card. Writes nothing except
    the case itself -- no charge happens until /confirm is called against it."""
    return reorder.propose_reorder(payload)


@app.post("/reorder/confirm")
def confirm_reorder(payload: ReorderConfirmRequest) -> ReorderResult:
    """Executes only if confirmed=True against a case /propose actually
    created, the risk-scaled confirmation requirement is met, and the
    duplicate-order guard passes on a fresh read right before charging."""
    return reorder.resolve_reorder(payload)


# ------------------------------------------------------- async re-engagement --


@app.post("/reengagement/fire")
def fire_reengagement(payload: ReengagementFireRequest) -> ReengagementResult:
    """Manual trigger for the demo (and for anything scheduling refill
    checks locally): publishes to Pub/Sub best-effort, then runs the same
    re-evaluation a real push subscription would -- the result reflects
    fresh Life Graph state, never whatever was true when this was queued."""
    scheduled_at = payload.scheduled_at or datetime.now(timezone.utc)
    reengagement.publish_refill_due_event(payload.user_id, payload.med_id, scheduled_at)
    return reengagement.evaluate_and_reengage(payload)


@app.post("/reengagement/pubsub-push")
def pubsub_push(envelope: dict) -> dict:
    """Target for a real Pub/Sub push subscription. Cloud Pub/Sub expects a
    2xx response to ack the message; anything else and it retries."""
    message = envelope.get("message", {})
    data = base64.b64decode(message.get("data", "")).decode("utf-8") if message.get("data") else "{}"
    body = json.loads(data)
    payload = ReengagementFireRequest(
        user_id=body["user_id"], med_id=body["med_id"], scheduled_at=body.get("scheduled_at")
    )
    result = reengagement.evaluate_and_reengage(payload)
    return {"acked": True, "status": result.status}
