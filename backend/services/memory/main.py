from typing import List

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from common.config import get_settings
from common.cors import add_dashboard_cors
from common.gcp_clients import ClientInitError
from common.health import run_checks
from common.logging_utils import get_logger

from . import life_graph as lg
from .clients import get_cloud_sql_engine, get_firestore_client
from .schemas import (
    AuditWrite,
    CasePatch,
    CaseWrite,
    DocumentWrite,
    MedicationCreate,
    MedicationPatch,
    PaymentWrite,
    PersonWrite,
    PreferenceWrite,
    ProfileWrite,
    ResolutionEventResolve,
)

logger = get_logger("memory")
settings = get_settings()

app = FastAPI(title="Lantern Memory Agent")
add_dashboard_cors(app)


@app.exception_handler(lg.TrustViolation)
async def _handle_trust_violation(request: Request, exc: lg.TrustViolation):
    return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content={"detail": str(exc)})


@app.exception_handler(lg.NotFound)
async def _handle_not_found(request: Request, exc: lg.NotFound):
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(exc)})


@app.exception_handler(lg.AlreadyResolved)
async def _handle_already_resolved(request: Request, exc: lg.AlreadyResolved):
    return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"detail": str(exc)})


@app.exception_handler(ClientInitError)
async def _handle_client_init_error(request: Request, exc: ClientInitError):
    return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"detail": str(exc)})


@app.get("/health")
def health() -> dict:
    return {"service": "memory", "status": "ok", "environment": settings.environment}


@app.get("/health/deep")
def health_deep() -> dict:
    checks = run_checks({"firestore": get_firestore_client, "cloud_sql_pgvector": get_cloud_sql_engine})
    return {"service": "memory", "checks": checks}


@app.get("/users/{user_id}/life-graph")
def life_graph_summary(user_id: str) -> dict:
    """What Lantern believes about this user — feeds the dashboard's Life Graph panel."""
    return lg.get_belief_summary(user_id)


# ------------------------------------------------------------------ profile --


@app.put("/users/{user_id}/profile")
def put_profile(user_id: str, payload: ProfileWrite) -> dict:
    return lg.write_profile(user_id, payload)


# -------------------------------------------------------------- medications --


@app.get("/users/{user_id}/medications")
def list_medications(user_id: str) -> List[dict]:
    return lg.list_medications(user_id)


@app.post("/users/{user_id}/medications", status_code=status.HTTP_201_CREATED)
def create_medication(user_id: str, payload: MedicationCreate) -> dict:
    return lg.create_medication(user_id, payload)


@app.get("/users/{user_id}/medications/{med_id}")
def get_medication(user_id: str, med_id: str) -> dict:
    return lg.get_medication(user_id, med_id)


@app.patch("/users/{user_id}/medications/{med_id}")
def patch_medication(user_id: str, med_id: str, payload: MedicationPatch) -> dict:
    return lg.update_medication(user_id, med_id, payload)


# ------------------------------------------------------------------ people --


@app.get("/users/{user_id}/people")
def list_people(user_id: str) -> List[dict]:
    return lg.list_people(user_id)


@app.post("/users/{user_id}/people", status_code=status.HTTP_201_CREATED)
def create_person(user_id: str, payload: PersonWrite) -> dict:
    return lg.create_person(user_id, payload)


# ----------------------------------------------------------------- payment --


@app.put("/users/{user_id}/payment")
def put_payment(user_id: str, payload: PaymentWrite) -> dict:
    return lg.write_payment(user_id, payload)


@app.get("/users/{user_id}/payment")
def get_payment(user_id: str) -> dict:
    """Unredacted, includes the real method_ref -- for services that
    actually need to charge, not for display."""
    payment = lg.get_payment(user_id)
    if payment is None:
        raise lg.NotFound(f"no payment method on file for user {user_id}")
    return payment


# --------------------------------------------------------------- documents --


@app.get("/users/{user_id}/documents")
def list_documents(user_id: str) -> List[dict]:
    return lg.list_documents(user_id)


@app.post("/users/{user_id}/documents", status_code=status.HTTP_201_CREATED)
def create_document(user_id: str, payload: DocumentWrite) -> dict:
    return lg.create_document(user_id, payload)


# ------------------------------------------------------------- preferences --


@app.get("/users/{user_id}/preferences")
def list_preferences(user_id: str) -> List[dict]:
    return lg.list_preferences(user_id)


@app.post("/users/{user_id}/preferences")
def write_preference(user_id: str, payload: PreferenceWrite) -> dict:
    return lg.write_preference(user_id, payload)


@app.get("/users/{user_id}/resolution-events")
def list_resolution_events(user_id: str, status_filter: str = "pending") -> List[dict]:
    return lg.list_resolution_events(user_id, status_filter=status_filter or None)


@app.post("/users/{user_id}/resolution-events/{event_id}/resolve")
def resolve_resolution_event(user_id: str, event_id: str, payload: ResolutionEventResolve) -> dict:
    return lg.resolve_resolution_event(user_id, event_id, payload)


# -------------------------------------------------------------------- cases --


@app.get("/users/{user_id}/cases")
def list_cases(user_id: str) -> List[dict]:
    return lg.list_cases(user_id)


@app.post("/users/{user_id}/cases", status_code=status.HTTP_201_CREATED)
def create_case(user_id: str, payload: CaseWrite) -> dict:
    return lg.create_case(user_id, payload)


@app.get("/users/{user_id}/cases/{case_id}")
def get_case(user_id: str, case_id: str) -> dict:
    return lg.get_case(user_id, case_id)


@app.patch("/users/{user_id}/cases/{case_id}")
def patch_case(user_id: str, case_id: str, payload: CasePatch) -> dict:
    return lg.update_case(user_id, case_id, payload)


# -------------------------------------------------------------------- audit --


@app.get("/users/{user_id}/audit")
def list_audit(user_id: str, limit: int = 50) -> List[dict]:
    return lg.list_audit(user_id, limit=limit)


@app.post("/users/{user_id}/audit", status_code=status.HTTP_201_CREATED)
def append_audit(user_id: str, payload: AuditWrite) -> dict:
    return lg.append_audit(user_id, payload)
