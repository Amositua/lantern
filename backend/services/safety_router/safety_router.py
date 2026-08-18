"""Safety Router -- runs on every turn, can veto any in-progress action.
Two triggers: a crisis phrase, or confidence too low to act on silently.
Either one halts and hands off instead of letting anything proceed.

The veto doesn't need Action's cooperation: it moves the case out of
"proposed" state directly, and Action's own confirm-time check (a case
has to still be "proposed" to execute) refuses it from there. One state
machine, enforced the same way regardless of who's asking.
"""
from typing import Optional

from common import memory_client
from common.config import get_settings

from .crisis_detection import CrisisType, detect_crisis_phrase
from .schemas import HandoffContact, SafetyCheckRequest, SafetyCheckResult

LOW_CONFIDENCE_THRESHOLD = 0.4


def check_turn(request: SafetyCheckRequest) -> SafetyCheckResult:
    if request.utterance:
        crisis = detect_crisis_phrase(request.utterance)
        if crisis is not None:
            return _halt(request, trigger="crisis_phrase", reason=_crisis_reason(crisis), veto_method=crisis, crisis=crisis)

    if request.confidence is not None and request.confidence < LOW_CONFIDENCE_THRESHOLD:
        reason = f"confidence {request.confidence:.2f} is below the safety threshold"
        return _halt(request, trigger="low_confidence", reason=reason, veto_method="low_confidence", crisis=None)

    return SafetyCheckResult(verdict="proceed")


def _halt(
    request: SafetyCheckRequest, trigger: str, reason: str, veto_method: str, crisis: Optional[CrisisType]
) -> SafetyCheckResult:
    vetoed = _veto_case_if_present(request.user_id, request.case_id, veto_method)
    return SafetyCheckResult(
        verdict="halt",
        trigger=trigger,
        reason=reason,
        handoff=_find_handoff_contact(request.user_id, crisis),
        vetoed_case_id=vetoed,
    )


def _crisis_reason(crisis: CrisisType) -> str:
    if crisis == "medical_emergency":
        return "that sounds like it could be a medical emergency"
    return "that sounds like it could be a mental health crisis"


def _veto_case_if_present(user_id: str, case_id: Optional[str], method: str) -> Optional[str]:
    if not case_id:
        return None
    try:
        case = memory_client.get_case(user_id, case_id)
    except memory_client.MemoryAgentError:
        return None
    if case.get("state") != "proposed":
        return None  # already resolved one way or another, nothing to veto

    memory_client.update_case(user_id, case_id, {"state": "halted_by_safety_router"})
    memory_client.append_audit(
        user_id,
        {
            "action": "safety_router_veto",
            "proposed": case.get("data", {}),
            "confirmed_by": "safety_router",
            "method": method,
            "result": "halted",
        },
    )
    return case_id


def _find_handoff_contact(user_id: str, crisis: Optional[CrisisType]) -> HandoffContact:
    try:
        people = memory_client.list_people(user_id)
    except memory_client.MemoryAgentError:
        people = []

    for person in people:
        roles = [r.lower() for r in person.get("roles", [])]
        if "emergency" in roles:
            return HandoffContact(
                name=person.get("name"),
                relation=person.get("relation"),
                contact=person.get("contact"),
                source="trusted_circle_emergency_contact",
            )

    settings = get_settings()
    if crisis == "mental_health_crisis" and settings.crisis_hotline_number:
        return HandoffContact(contact=settings.crisis_hotline_number, source="crisis_hotline")

    return HandoffContact(contact=settings.national_emergency_number, source="national_emergency_number")
