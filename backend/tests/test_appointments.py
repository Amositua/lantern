import pytest

from common.memory_client import MemoryAgentError
from services.action import appointments
from services.action.appointments_schemas import AppointmentConfirmRequest, AppointmentProposeRequest
from services.action.clinic_client import ClinicError, ScheduleResult

from .memory_fakes import FakeMemoryStore

CARDIOLOGY = {
    "id": "appt-cardio",
    "provider": "City General Hospital",
    "purpose": "cardiology follow-up",
    "scheduled_for": "Thursday the 14th at 10:30am",
    "location": None,
    "status": "scheduled",
}


class FakeClinicClient:
    def __init__(self):
        self.confirmed = []
        self.rescheduled = []
        self.cancelled = []

    def confirm_attendance(self, provider, appointment_ref):
        self.confirmed.append((provider, appointment_ref))
        return ScheduleResult(confirmation_ref="sched-test-1", new_time=appointment_ref)

    def reschedule(self, provider, appointment_ref, new_time):
        self.rescheduled.append((provider, appointment_ref, new_time))
        return ScheduleResult(confirmation_ref="sched-test-2", new_time=new_time)

    def cancel(self, provider, appointment_ref):
        self.cancelled.append((provider, appointment_ref))


def _wire(monkeypatch, store, clinic=None):
    monkeypatch.setattr(appointments.memory_client, "get_appointment", store.get_appointment)
    monkeypatch.setattr(appointments.memory_client, "update_appointment", store.update_appointment)
    monkeypatch.setattr(appointments.memory_client, "create_case", store.create_case)
    monkeypatch.setattr(appointments.memory_client, "get_case", store.get_case)
    monkeypatch.setattr(appointments.memory_client, "update_case", store.update_case)
    monkeypatch.setattr(appointments.memory_client, "append_audit", store.append_audit)
    monkeypatch.setattr(appointments, "get_clinic_client", lambda: clinic or FakeClinicClient())


def test_propose_confirm_attendance_reads_back_provider_and_time(monkeypatch):
    store = FakeMemoryStore(appointment=CARDIOLOGY)
    _wire(monkeypatch, store)

    proposal = appointments.propose_appointment_action(
        AppointmentProposeRequest(user_id="u1", appointment_id="appt-cardio", intent="confirm_attendance")
    )

    assert "City General Hospital" in proposal.read_back
    assert "Thursday the 14th" in proposal.read_back
    assert store.cases[proposal.case_id]["state"] == "proposed"


def test_reschedule_requires_a_new_time_at_the_schema_level():
    with pytest.raises(Exception):
        AppointmentProposeRequest(user_id="u1", appointment_id="appt-cardio", intent="reschedule")


def test_confirming_attendance_calls_the_clinic_and_updates_status(monkeypatch):
    store = FakeMemoryStore(appointment=CARDIOLOGY)
    clinic = FakeClinicClient()
    _wire(monkeypatch, store, clinic=clinic)

    proposal = appointments.propose_appointment_action(
        AppointmentProposeRequest(user_id="u1", appointment_id="appt-cardio", intent="confirm_attendance")
    )
    result = appointments.resolve_appointment_action(
        AppointmentConfirmRequest(user_id="u1", case_id=proposal.case_id, confirmed=True)
    )

    assert result.status == "executed"
    assert clinic.confirmed == [("City General Hospital", "appt-cardio")]
    assert store.appointments["appt-cardio"]["status"] == "confirmed"


def test_rescheduling_updates_scheduled_for_and_reverifies(monkeypatch):
    store = FakeMemoryStore(appointment=CARDIOLOGY)
    clinic = FakeClinicClient()
    _wire(monkeypatch, store, clinic=clinic)

    proposal = appointments.propose_appointment_action(
        AppointmentProposeRequest(
            user_id="u1", appointment_id="appt-cardio", intent="reschedule", new_time="Friday the 15th at 9am"
        )
    )
    result = appointments.resolve_appointment_action(
        AppointmentConfirmRequest(user_id="u1", case_id=proposal.case_id, confirmed=True)
    )

    assert result.status == "executed"
    assert clinic.rescheduled == [("City General Hospital", "appt-cardio", "Friday the 15th at 9am")]
    assert store.appointments["appt-cardio"]["scheduled_for"] == "Friday the 15th at 9am"
    assert store.appointments["appt-cardio"]["verification"]["method"] == "clinic_verified"


def test_declining_does_not_call_the_clinic(monkeypatch):
    store = FakeMemoryStore(appointment=CARDIOLOGY)
    clinic = FakeClinicClient()
    _wire(monkeypatch, store, clinic=clinic)

    proposal = appointments.propose_appointment_action(
        AppointmentProposeRequest(user_id="u1", appointment_id="appt-cardio", intent="confirm_attendance")
    )
    result = appointments.resolve_appointment_action(
        AppointmentConfirmRequest(user_id="u1", case_id=proposal.case_id, confirmed=False)
    )

    assert result.status == "declined"
    assert clinic.confirmed == []


def test_a_case_that_was_never_proposed_cannot_be_confirmed(monkeypatch):
    store = FakeMemoryStore(appointment=CARDIOLOGY)
    _wire(monkeypatch, store)

    with pytest.raises(MemoryAgentError):
        appointments.resolve_appointment_action(
            AppointmentConfirmRequest(user_id="u1", case_id="never-existed", confirmed=True)
        )


def test_a_clinic_failure_is_audited_and_surfaced(monkeypatch):
    class AlwaysFailsClinic(FakeClinicClient):
        def confirm_attendance(self, provider, appointment_ref):
            raise ClinicError("clinic system unreachable")

    store = FakeMemoryStore(appointment=CARDIOLOGY)
    _wire(monkeypatch, store, clinic=AlwaysFailsClinic())

    proposal = appointments.propose_appointment_action(
        AppointmentProposeRequest(user_id="u1", appointment_id="appt-cardio", intent="confirm_attendance")
    )
    with pytest.raises(appointments.AppointmentActionError):
        appointments.resolve_appointment_action(
            AppointmentConfirmRequest(user_id="u1", case_id=proposal.case_id, confirmed=True)
        )

    assert "failed" in store.audit_log[-1]["result"]
