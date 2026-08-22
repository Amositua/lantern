"""Proactive re-engagement. The event means "re-assess," never "reorder" --
it carries a neutral scheduled_at, not the med's identity, so every fire
re-reads Life Graph state fresh: Rx changed, already reordered, or
discontinued all abort; only a still-valid, still-due med reaches
propose-confirm.

Anti-nag: an unanswered nudge escalates its count rather than repeating,
and past a threshold hands off to the trusted circle instead. Quiet
hours defer instead of interrupting sleep. Other due meds fold into the
same message instead of firing their own separate contact.
"""
import json
from datetime import datetime, timezone
from typing import List, Optional

from common import memory_client
from common.logging_utils import get_logger

from . import reorder
from .reengagement_schemas import ReengagementFireRequest, ReengagementResult
from .reorder_schemas import ReorderProposeRequest

logger = get_logger("action.reengagement")

REENGAGEMENT_TASK = "medication_reengagement"
OPEN_STATES = {"nudged"}
ESCALATE_AFTER_NUDGES = 3
DEFAULT_QUIET_HOURS = (21, 7)  # 9pm - 7am, used when the profile doesn't set one


def evaluate_and_reengage(request: ReengagementFireRequest) -> ReengagementResult:
    scheduled_at = request.scheduled_at or datetime.now(timezone.utc)
    medication = memory_client.get_medication(request.user_id, request.med_id)
    open_case = _find_open_case(request.user_id, request.med_id)

    if medication.get("discontinued"):
        _close_case(request.user_id, open_case)
        _audit(request.user_id, request.med_id, "aborted_discontinued", None)
        return ReengagementResult(
            status="aborted_discontinued",
            med_id=request.med_id,
            message=f"{medication['name']} is marked discontinued -- not reordering.",
        )

    if _rx_changed_since(medication, scheduled_at):
        _close_case(request.user_id, open_case)
        _audit(request.user_id, request.med_id, "aborted_rx_changed", None)
        return ReengagementResult(
            status="aborted_rx_changed",
            med_id=request.med_id,
            message=f"{medication['name']}'s details changed since this was scheduled -- checking with you before doing anything.",
        )

    if reorder._is_duplicate(medication):
        _close_case(request.user_id, open_case)
        _audit(request.user_id, request.med_id, "aborted_already_reordered", None)
        return ReengagementResult(
            status="aborted_already_reordered",
            med_id=request.med_id,
            message=f"Looks like {medication['name']} was already reordered recently.",
        )

    if _in_quiet_hours(request.user_id):
        _audit(request.user_id, request.med_id, "deferred_quiet_hours", None)
        return ReengagementResult(
            status="deferred_quiet_hours",
            med_id=request.med_id,
            message="It's quiet hours -- holding off until morning instead of reaching out now.",
        )

    nudge_count = (open_case["data"].get("nudge_count", 0) if open_case else 0) + 1

    if nudge_count > ESCALATE_AFTER_NUDGES:
        contact = _find_trusted_circle_contact(request.user_id)
        if open_case:
            memory_client.update_case(
                request.user_id, open_case["id"], {"state": "escalated_to_trusted_circle", "data": {**open_case["data"], "nudge_count": nudge_count}}
            )
        contact_name = contact.get("name") if contact else None
        _audit(request.user_id, request.med_id, "escalated_to_trusted_circle", contact_name)
        return ReengagementResult(
            status="escalated_to_trusted_circle",
            med_id=request.med_id,
            message=(
                f"{medication['name']} has gone unanswered a few times -- looping in "
                f"{contact_name or 'your trusted contact'} instead of asking again."
            ),
        )

    also_due = _other_due_med_names(request.user_id, request.med_id)
    proposal = reorder.propose_reorder(ReorderProposeRequest(user_id=request.user_id, med_id=request.med_id))

    case_data = {
        "med_id": request.med_id,
        "nudge_count": nudge_count,
        "reorder_case_id": proposal.case_id,
        "last_nudge_at": _now_iso(),
    }
    if open_case:
        memory_client.update_case(request.user_id, open_case["id"], {"state": "nudged", "data": case_data})
        case_id = open_case["id"]
    else:
        created = memory_client.create_case(
            request.user_id, {"task": REENGAGEMENT_TASK, "state": "nudged", "data": case_data}
        )
        case_id = created["id"]

    message = proposal.read_back
    if also_due:
        message += f" (Also due: {', '.join(also_due)}.)"

    _audit(request.user_id, request.med_id, "proposed", None, nudge_count=nudge_count)

    return ReengagementResult(
        status="proposed", med_id=request.med_id, message=message, case_id=case_id, proposal=proposal, also_due=also_due
    )


def publish_refill_due_event(user_id: str, med_id: str, scheduled_at: datetime) -> Optional[str]:
    """Best-effort -- Pub/Sub is how a real deployment schedules these, but
    the actual safety logic above never depends on the publish succeeding."""
    try:
        from common.gcp_clients import get_pubsub_publisher, topic_path

        publisher = get_pubsub_publisher()
        path = topic_path("refill-due")
        payload = json.dumps({"user_id": user_id, "med_id": med_id, "scheduled_at": scheduled_at.isoformat()}).encode("utf-8")
        future = publisher.publish(path, payload)
        return future.result(timeout=5)
    except Exception:  # noqa: BLE001 - publishing is a nice-to-have here, not a dependency
        logger.warning("could not publish the refill-due event to Pub/Sub", exc_info=True)
        return None


def _find_open_case(user_id: str, med_id: str) -> Optional[dict]:
    for case in memory_client.list_cases(user_id):
        if case.get("task") == REENGAGEMENT_TASK and case.get("state") in OPEN_STATES and case.get("data", {}).get("med_id") == med_id:
            return case
    return None


def _close_case(user_id: str, case: Optional[dict]) -> None:
    if case:
        memory_client.update_case(user_id, case["id"], {"state": "resolved"})


def _rx_changed_since(medication: dict, scheduled_at: datetime) -> bool:
    last_confirmed = reorder._parse_datetime(medication.get("last_confirmed"))
    if last_confirmed is None:
        return False
    return last_confirmed > scheduled_at


def _in_quiet_hours(user_id: str) -> bool:
    try:
        life_graph = memory_client.get_life_graph(user_id)
    except memory_client.MemoryAgentError:
        return False
    profile = life_graph.get("profile") or {}
    start = profile.get("quiet_hours_start")
    end = profile.get("quiet_hours_end")
    if start is None or end is None:
        start, end = DEFAULT_QUIET_HOURS

    hour = datetime.now(timezone.utc).hour
    if start <= end:
        return start <= hour < end
    return hour >= start or hour < end  # wraps past midnight


def _other_due_med_names(user_id: str, med_id: str) -> List[str]:
    due = []
    for med in memory_client.list_medications(user_id):
        if med["id"] == med_id:
            continue
        if _is_due(med):
            due.append(med["name"])
    return due


def _is_due(medication: dict) -> bool:
    last_refill = reorder._parse_datetime(medication.get("last_refill"))
    cadence = medication.get("cadence")
    if last_refill is None or not cadence:
        return False
    return (datetime.now(timezone.utc) - last_refill).days >= cadence


def _find_trusted_circle_contact(user_id: str) -> dict:
    try:
        people = memory_client.list_people(user_id)
    except memory_client.MemoryAgentError:
        people = []
    for person in people:
        roles = [r.lower() for r in person.get("roles", [])]
        if "trusted_circle" in roles or "caregiver" in roles:
            return person
    return {}


def _audit(user_id: str, med_id: str, result: str, escalated_to: Optional[str], **extra) -> None:
    memory_client.append_audit(
        user_id,
        {
            "action": "medication_reengagement",
            "proposed": {"med_id": med_id, **extra},
            "confirmed_by": escalated_to or "system",
            "method": "pubsub_reengagement",
            "result": result,
        },
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
