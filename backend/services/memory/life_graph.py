"""Life Graph read/write logic. Every write to a user's record goes
through here.

Two rules that matter: a med's name/dose can't change without a
verification block from the trusted-enrollment path, and a preference
that's already been confirmed a few times won't get silently overwritten
by a contradicting value — that raises a resolution event instead.

`db` param is optional everywhere so tests can pass a fake; real callers
just leave it out.
"""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .clients import get_firestore_client
from .schemas import (
    AppointmentCreate,
    AppointmentPatch,
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
from .vector_store import get_vector_store

HARDENED_CONFIDENCE = 0.75
HARDENED_OBSERVATIONS = 3
INITIAL_CONFIDENCE = 0.4
CONFIDENCE_STEP = 0.2

ASCENDING = "ASCENDING"
DESCENDING = "DESCENDING"


class TrustViolation(PermissionError):
    """Tried to change a safety-critical fact without trusted evidence."""


class NotFound(LookupError):
    pass


class AlreadyResolved(ValueError):
    pass


def now() -> datetime:
    return datetime.now(timezone.utc)


def _db(db):
    return db or get_firestore_client()


def _vector_store(store):
    return store or get_vector_store()


def _user_ref(db, user_id: str):
    return db.collection("users").document(user_id)


# ---------------------------------------------------------------- profile --


def write_profile(user_id: str, profile: ProfileWrite, db=None) -> dict:
    db = _db(db)
    data = profile.model_dump(exclude_unset=True)
    data["updated_at"] = now()
    _user_ref(db, user_id).set(data, merge=True)
    return _user_ref(db, user_id).get().to_dict()


# ------------------------------------------------------------- medications --


def create_medication(user_id: str, med: MedicationCreate, db=None) -> dict:
    db = _db(db)
    med_ref = _user_ref(db, user_id).collection("medications").document()
    ts = now()
    doc = {
        "name": med.name,
        "dose": med.dose,
        "condition": med.condition,
        "pharmacy_ref": med.pharmacy_ref,
        "cadence": med.cadence,
        "rx_ref": med.rx_ref,
        "last_refill": None,
        "verification": med.verification.model_dump(mode="json"),
        "created_at": ts,
        "last_confirmed": ts,
    }
    med_ref.set(doc)
    return {"id": med_ref.id, **doc}


def update_medication(user_id: str, med_id: str, patch: MedicationPatch, db=None) -> dict:
    db = _db(db)
    med_ref = _user_ref(db, user_id).collection("medications").document(med_id)
    snapshot = med_ref.get()
    if not snapshot.exists:
        raise NotFound(f"medication {med_id} not found")

    touches_identity = patch.name is not None or patch.dose is not None or patch.discontinued is not None
    if touches_identity and patch.verification is None:
        raise TrustViolation(
            "changing a medication's name, dose, or discontinued status requires a "
            "verification block — re-enter the trusted-enrollment path (prescription, "
            "pharmacist, trusted-circle, or dispensing-record verification)"
        )

    updates: Dict[str, Any] = patch.model_dump(exclude_unset=True, exclude={"verification"})
    updates["last_confirmed"] = now()
    if patch.verification is not None:
        updates["verification"] = patch.verification.model_dump(mode="json")

    med_ref.update(updates)
    return {"id": med_id, **med_ref.get().to_dict()}


def get_medication(user_id: str, med_id: str, db=None) -> dict:
    db = _db(db)
    snapshot = _user_ref(db, user_id).collection("medications").document(med_id).get()
    if not snapshot.exists:
        raise NotFound(f"medication {med_id} not found")
    return {"id": med_id, **snapshot.to_dict()}


def list_medications(user_id: str, db=None) -> List[dict]:
    db = _db(db)
    return [{"id": d.id, **d.to_dict()} for d in _user_ref(db, user_id).collection("medications").stream()]


# ------------------------------------------------------------ appointments --


def create_appointment(user_id: str, appointment: AppointmentCreate, db=None) -> dict:
    db = _db(db)
    appt_ref = _user_ref(db, user_id).collection("appointments").document()
    ts = now()
    doc = {
        "provider": appointment.provider,
        "purpose": appointment.purpose,
        "scheduled_for": appointment.scheduled_for,
        "location": appointment.location,
        "source_document_id": appointment.source_document_id,
        "status": "scheduled",
        "verification": appointment.verification.model_dump(mode="json"),
        "created_at": ts,
        "last_confirmed": ts,
    }
    appt_ref.set(doc)
    return {"id": appt_ref.id, **doc}


def update_appointment(user_id: str, appointment_id: str, patch: AppointmentPatch, db=None) -> dict:
    db = _db(db)
    appt_ref = _user_ref(db, user_id).collection("appointments").document(appointment_id)
    snapshot = appt_ref.get()
    if not snapshot.exists:
        raise NotFound(f"appointment {appointment_id} not found")

    touches_identity = patch.provider is not None or patch.scheduled_for is not None
    if touches_identity and patch.verification is None:
        raise TrustViolation(
            "changing an appointment's provider or time requires a verification block — "
            "re-enter the trusted-enrollment path (document import, clinic, or "
            "trusted-circle verification)"
        )

    updates: Dict[str, Any] = patch.model_dump(exclude_unset=True, exclude={"verification"})
    updates["last_confirmed"] = now()
    if patch.verification is not None:
        updates["verification"] = patch.verification.model_dump(mode="json")

    appt_ref.update(updates)
    return {"id": appointment_id, **appt_ref.get().to_dict()}


def get_appointment(user_id: str, appointment_id: str, db=None) -> dict:
    db = _db(db)
    snapshot = _user_ref(db, user_id).collection("appointments").document(appointment_id).get()
    if not snapshot.exists:
        raise NotFound(f"appointment {appointment_id} not found")
    return {"id": appointment_id, **snapshot.to_dict()}


def list_appointments(user_id: str, db=None) -> List[dict]:
    db = _db(db)
    return [{"id": d.id, **d.to_dict()} for d in _user_ref(db, user_id).collection("appointments").stream()]


# ----------------------------------------------------------------- people --


def create_person(user_id: str, person: PersonWrite, db=None) -> dict:
    db = _db(db)
    person_ref = _user_ref(db, user_id).collection("people").document()
    doc = person.model_dump()
    doc["created_at"] = now()
    person_ref.set(doc)
    return {"id": person_ref.id, **doc}


def list_people(user_id: str, db=None) -> List[dict]:
    db = _db(db)
    return [{"id": d.id, **d.to_dict()} for d in _user_ref(db, user_id).collection("people").stream()]


# ---------------------------------------------------------------- payment --


def write_payment(user_id: str, payment: PaymentWrite, db=None) -> dict:
    db = _db(db)
    ts = now()
    doc = {
        "method_ref": payment.method_ref,
        "card_last4": payment.card_last4,
        "card_bank": payment.card_bank,
        "per_transaction_cap": payment.per_transaction_cap,
        "daily_cap": payment.daily_cap,
        "never_auto_categories": payment.never_auto_categories,
        "verification": payment.verification.model_dump(mode="json"),
        "last_confirmed": ts,
    }
    _user_ref(db, user_id).set({"payment": doc}, merge=True)
    return doc


def get_payment(user_id: str, db=None) -> Optional[dict]:
    """Unredacted -- includes the real method_ref. For service-to-service use
    (Action needs the actual token to charge); the dashboard reads the
    redacted version through get_belief_summary instead."""
    db = _db(db)
    user_data = _user_ref(db, user_id).get().to_dict() or {}
    return user_data.get("payment")


# -------------------------------------------------------------- documents --


def create_document(user_id: str, document: DocumentWrite, db=None, store=None) -> dict:
    db = _db(db)
    doc_ref = _user_ref(db, user_id).collection("documents").document()
    doc = document.model_dump()
    doc["created_at"] = now()
    doc_ref.set(doc)

    # text is what makes this document retrievable later -- no text, no
    # embedding, it just sits in Firestore as metadata like before.
    if document.text:
        _vector_store(store).upsert(user_id, doc_ref.id, document.text)

    return {"id": doc_ref.id, **doc}


def list_documents(user_id: str, db=None) -> List[dict]:
    db = _db(db)
    return [{"id": d.id, **d.to_dict()} for d in _user_ref(db, user_id).collection("documents").stream()]


def search_documents(user_id: str, query: str, top_k: int = 3, db=None, store=None) -> List[dict]:
    db = _db(db)
    docs_ref = _user_ref(db, user_id).collection("documents")
    results = []
    for document_id, excerpt, distance in _vector_store(store).search(user_id, query, top_k=top_k):
        snapshot = docs_ref.document(document_id).get()
        if not snapshot.exists:
            continue
        metadata = snapshot.to_dict()
        results.append(
            {
                "document_id": document_id,
                "type": metadata.get("type"),
                "uri": metadata.get("uri"),
                "excerpt": excerpt,
                "distance": distance,
            }
        )
    return results


# ------------------------------------------------------------ preferences --


def _is_hardened(pref: dict) -> bool:
    return (
        bool(pref.get("hardened"))
        or pref.get("confidence", 0) >= HARDENED_CONFIDENCE
        or pref.get("observation_count", 0) >= HARDENED_OBSERVATIONS
    )


def write_preference(user_id: str, pref: PreferenceWrite, db=None) -> dict:
    db = _db(db)
    pref_ref = _user_ref(db, user_id).collection("preferences").document(pref.domain)
    ts = now()

    pref_ref.collection("history").document().set(
        {
            "value": pref.value,
            "source_utterance": pref.source_utterance,
            "is_override": pref.is_override,
            "ts": ts,
        }
    )

    if pref.is_override:
        existing = pref_ref.get()
        return {
            "applied": False,
            "reason": "one_off_override",
            "standing_preference": existing.to_dict() if existing.exists else None,
        }

    snapshot = pref_ref.get()
    if not snapshot.exists:
        doc = {
            "domain": pref.domain,
            "value": pref.value,
            "source_utterance": pref.source_utterance,
            "confidence": INITIAL_CONFIDENCE,
            "observation_count": 1,
            "last_confirmed": ts,
            "is_override": False,
            "hardened": False,
            "created_at": ts,
        }
        pref_ref.set(doc)
        return {"applied": True, "reason": "provisional_created", "standing_preference": doc}

    existing = snapshot.to_dict()

    if pref.value == existing.get("value"):
        new_count = existing.get("observation_count", 0) + 1
        new_confidence = min(1.0, existing.get("confidence", INITIAL_CONFIDENCE) + CONFIDENCE_STEP)
        updates = {
            "observation_count": new_count,
            "confidence": new_confidence,
            "last_confirmed": ts,
            "source_utterance": pref.source_utterance,
            "hardened": new_confidence >= HARDENED_CONFIDENCE or new_count >= HARDENED_OBSERVATIONS,
        }
        pref_ref.update(updates)
        return {"applied": True, "reason": "confirmed", "standing_preference": {**existing, **updates}}

    if _is_hardened(existing):
        event_ref = _user_ref(db, user_id).collection("resolution_events").document()
        event = {
            "domain": pref.domain,
            "existing_value": existing.get("value"),
            "existing_confidence": existing.get("confidence"),
            "new_value": pref.value,
            "new_source_utterance": pref.source_utterance,
            "status": "pending",
            "created_at": ts,
        }
        event_ref.set(event)
        return {
            "applied": False,
            "reason": "contradiction",
            "resolution_event": {"id": event_ref.id, **event},
            "standing_preference": existing,
        }

    # still provisional, so just revise it — a single mishear shouldn't
    # have hardened into truth yet anyway
    doc = {
        "domain": pref.domain,
        "value": pref.value,
        "source_utterance": pref.source_utterance,
        "confidence": INITIAL_CONFIDENCE,
        "observation_count": 1,
        "last_confirmed": ts,
        "is_override": False,
        "hardened": False,
        "created_at": existing.get("created_at", ts),
    }
    pref_ref.set(doc)
    return {"applied": True, "reason": "provisional_revised", "standing_preference": doc}


def list_preferences(user_id: str, db=None) -> List[dict]:
    db = _db(db)
    return [{"id": d.id, **d.to_dict()} for d in _user_ref(db, user_id).collection("preferences").stream()]


def list_resolution_events(user_id: str, status_filter: Optional[str] = "pending", db=None) -> List[dict]:
    db = _db(db)
    collection = _user_ref(db, user_id).collection("resolution_events")
    query = collection.where("status", "==", status_filter) if status_filter else collection
    return [{"id": d.id, **d.to_dict()} for d in query.stream()]


def resolve_resolution_event(user_id: str, event_id: str, resolution: ResolutionEventResolve, db=None) -> dict:
    db = _db(db)
    event_ref = _user_ref(db, user_id).collection("resolution_events").document(event_id)
    snapshot = event_ref.get()
    if not snapshot.exists:
        raise NotFound(f"resolution event {event_id} not found")
    event = snapshot.to_dict()
    if event.get("status") != "pending":
        raise AlreadyResolved(f"resolution event {event_id} was already resolved")

    ts = now()
    pref_ref = _user_ref(db, user_id).collection("preferences").document(event["domain"])

    if resolution.decision == "accept_new":
        doc = {
            "domain": event["domain"],
            "value": event["new_value"],
            "source_utterance": event["new_source_utterance"],
            "confidence": INITIAL_CONFIDENCE,
            "observation_count": 1,
            "last_confirmed": ts,
            "is_override": False,
            "hardened": False,
            "created_at": ts,
        }
        pref_ref.set(doc)
    else:
        pref_ref.update({"last_confirmed": ts})

    event_ref.update(
        {"status": "resolved", "decision": resolution.decision, "resolved_by": resolution.resolved_by, "resolved_at": ts}
    )
    return {"id": event_id, "decision": resolution.decision}


# ---------------------------------------------------------------- cases --


def create_case(user_id: str, case: CaseWrite, db=None) -> dict:
    db = _db(db)
    case_ref = _user_ref(db, user_id).collection("cases").document()
    doc = case.model_dump()
    doc["created_at"] = now()
    case_ref.set(doc)
    return {"id": case_ref.id, **doc}


def update_case(user_id: str, case_id: str, patch: CasePatch, db=None) -> dict:
    db = _db(db)
    case_ref = _user_ref(db, user_id).collection("cases").document(case_id)
    if not case_ref.get().exists:
        raise NotFound(f"case {case_id} not found")
    updates = patch.model_dump(exclude_unset=True)
    updates["updated_at"] = now()
    case_ref.update(updates)
    return {"id": case_id, **case_ref.get().to_dict()}


def get_case(user_id: str, case_id: str, db=None) -> dict:
    db = _db(db)
    snapshot = _user_ref(db, user_id).collection("cases").document(case_id).get()
    if not snapshot.exists:
        raise NotFound(f"case {case_id} not found")
    return {"id": case_id, **snapshot.to_dict()}


def list_cases(user_id: str, db=None) -> List[dict]:
    db = _db(db)
    return [{"id": d.id, **d.to_dict()} for d in _user_ref(db, user_id).collection("cases").stream()]


# ---------------------------------------------------------------- audit --


def append_audit(user_id: str, audit: AuditWrite, db=None) -> dict:
    db = _db(db)
    audit_ref = _user_ref(db, user_id).collection("audit").document()
    doc = audit.model_dump()
    doc["ts"] = now()
    audit_ref.set(doc)
    return {"id": audit_ref.id, **doc}


def list_audit(user_id: str, limit: int = 50, db=None) -> List[dict]:
    db = _db(db)
    query = _user_ref(db, user_id).collection("audit").order_by("ts", direction=DESCENDING).limit(limit)
    return [{"id": d.id, **d.to_dict()} for d in query.stream()]


# ------------------------------------------------------- belief summary --


def get_belief_summary(user_id: str, db=None) -> dict:
    """Feeds the dashboard's "what Lantern believes about you" panel."""
    db = _db(db)
    user_data = _user_ref(db, user_id).get().to_dict() or {}

    payment = user_data.get("payment")
    payment_summary = None
    if payment:
        payment_summary = {
            "method_ref_present": bool(payment.get("method_ref")),
            "per_transaction_cap": payment.get("per_transaction_cap"),
            "daily_cap": payment.get("daily_cap"),
            "never_auto_categories": payment.get("never_auto_categories", []),
            "last_confirmed": payment.get("last_confirmed"),
        }

    return {
        "profile": {
            "name": user_data.get("name"),
            "language": user_data.get("language"),
            "literacy_level": user_data.get("literacy_level"),
            "abilities": user_data.get("abilities"),
            "pacing_pref": user_data.get("pacing_pref"),
        },
        "medications": list_medications(user_id, db=db),
        "appointments": list_appointments(user_id, db=db),
        "people": list_people(user_id, db=db),
        "payment": payment_summary,
        "preferences": list_preferences(user_id, db=db),
        "pending_resolution_events": list_resolution_events(user_id, db=db),
        "recent_audit": list_audit(user_id, db=db),
    }
