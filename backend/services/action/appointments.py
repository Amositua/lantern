"""Appointment actions: propose (read back what's about to change), confirm,
execute. No payment sits behind this one, unlike reorder.py/bills.py -- so
there's no risk-scaled confirmation tier to pick, but it's still medical
and still goes through the same propose-confirm-execute shape rather than
acting straight from a voice turn.
"""
from common import memory_client

from .appointments_schemas import AppointmentConfirmRequest, AppointmentProposal, AppointmentProposeRequest, AppointmentResult
from .clinic_client import ClinicError, get_clinic_client


class AppointmentActionError(RuntimeError):
    pass


def propose_appointment_action(request: AppointmentProposeRequest) -> AppointmentProposal:
    appointment = memory_client.get_appointment(request.user_id, request.appointment_id)

    case = memory_client.create_case(
        request.user_id,
        {
            "task": "appointment_action",
            "state": "proposed",
            "data": {
                "appointment_id": request.appointment_id,
                "provider": appointment["provider"],
                "intent": request.intent,
                "new_time": request.new_time,
            },
        },
    )

    read_back = _read_back(appointment, request.intent, request.new_time)

    return AppointmentProposal(
        case_id=case["id"],
        appointment_id=request.appointment_id,
        provider=appointment["provider"],
        intent=request.intent,
        read_back=read_back,
    )


def resolve_appointment_action(request: AppointmentConfirmRequest) -> AppointmentResult:
    case = memory_client.get_case(request.user_id, request.case_id)
    if case.get("task") != "appointment_action":
        raise AppointmentActionError(f"case {request.case_id} is not an appointment action")
    if case.get("state") != "proposed":
        raise AppointmentActionError(f"case {request.case_id} is not awaiting confirmation (state={case.get('state')})")

    data = case["data"]
    appointment_id = data["appointment_id"]
    intent = data["intent"]
    idempotency_key = f"appointment_{case['id']}"

    if not request.confirmed:
        memory_client.update_case(request.user_id, case["id"], {"state": "declined"})
        _write_audit(request.user_id, data, request.confirmed_by, "declined", idempotency_key)
        return AppointmentResult(status="declined", message="Okay, leaving it as it was.")

    appointment = memory_client.get_appointment(request.user_id, appointment_id)
    clinic = get_clinic_client()

    try:
        if intent == "confirm_attendance":
            outcome = clinic.confirm_attendance(appointment["provider"], appointment_id)
            memory_client.update_appointment(request.user_id, appointment_id, {"status": "confirmed"})
            message = f"Done -- you're confirmed for {appointment['provider']}."
        elif intent == "reschedule":
            outcome = clinic.reschedule(appointment["provider"], appointment_id, data["new_time"])
            memory_client.update_appointment(
                request.user_id,
                appointment_id,
                {
                    "scheduled_for": data["new_time"],
                    "status": "rescheduled",
                    "verification": {"method": "clinic_verified", "verified_by": f"{appointment['provider']} scheduling system"},
                },
            )
            message = f"Done -- {appointment['provider']} is rescheduled to {data['new_time']}."
        else:  # cancel
            clinic.cancel(appointment["provider"], appointment_id)
            memory_client.update_appointment(request.user_id, appointment_id, {"status": "cancelled", "cancelled": True})
            outcome = None
            message = f"Done -- your {appointment['provider']} appointment is cancelled."
    except ClinicError as exc:
        memory_client.update_case(request.user_id, case["id"], {"state": "failed"})
        _write_audit(request.user_id, data, request.confirmed_by, f"failed: {exc}", idempotency_key)
        raise AppointmentActionError(str(exc)) from exc

    memory_client.update_case(request.user_id, case["id"], {"state": "executed"})
    _write_audit(request.user_id, data, request.confirmed_by, "success", idempotency_key)

    return AppointmentResult(
        status="executed", message=message, confirmation_ref=outcome.confirmation_ref if outcome else None
    )


def _read_back(appointment: dict, intent: str, new_time: str) -> str:
    provider = appointment["provider"]
    when = appointment.get("scheduled_for") or "your upcoming appointment"
    if intent == "confirm_attendance":
        return f"That's your {provider} appointment, {when}. Confirm you'll be there?"
    if intent == "reschedule":
        return f"Move your {provider} appointment from {when} to {new_time}?"
    return f"Cancel your {provider} appointment, {when}?"


def _write_audit(user_id: str, proposed: dict, confirmed_by: str, result: str, idempotency_key: str) -> None:
    memory_client.append_audit(
        user_id,
        {
            "action": "appointment_action",
            "proposed": proposed,
            "confirmed_by": confirmed_by,
            "method": proposed.get("intent"),
            "result": result,
            "idempotency_key": idempotency_key,
        },
    )
