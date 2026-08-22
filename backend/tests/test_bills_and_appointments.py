import pytest

from services.memory import life_graph as lg
from services.memory.schemas import (
    AppointmentCreate,
    AppointmentPatch,
    AppointmentVerification,
    BillCreate,
    BillPatch,
    BillVerification,
)

from .fake_firestore import FakeFirestoreClient


@pytest.fixture
def db():
    return FakeFirestoreClient()


def _bill_verified() -> BillVerification:
    return BillVerification(method="account_statement_import", verified_by="statement import")


def _appt_verified() -> AppointmentVerification:
    return AppointmentVerification(method="document_import", verified_by="cardiology letter")


# --------------------------------------------------------------------- bills --


def test_bill_create_without_verification_is_rejected_by_schema():
    with pytest.raises(Exception):
        BillCreate(provider="EKEDC", category="electricity", account_ref="ACC-1")


def test_bill_account_change_outside_enrollment_path_is_rejected(db):
    created = lg.create_bill(
        "u1", BillCreate(provider="EKEDC", category="electricity", account_ref="ACC-1", verification=_bill_verified()), db=db
    )

    with pytest.raises(lg.TrustViolation):
        lg.update_bill("u1", created["id"], BillPatch(account_ref="ACC-2"), db=db)

    unchanged = lg.get_bill("u1", created["id"], db=db)
    assert unchanged["account_ref"] == "ACC-1"


def test_bill_account_change_with_verification_is_allowed(db):
    created = lg.create_bill(
        "u1", BillCreate(provider="EKEDC", category="electricity", account_ref="ACC-1", verification=_bill_verified()), db=db
    )
    updated = lg.update_bill("u1", created["id"], BillPatch(account_ref="ACC-2", verification=_bill_verified()), db=db)
    assert updated["account_ref"] == "ACC-2"


def test_bill_non_identity_field_can_change_without_verification(db):
    created = lg.create_bill(
        "u1", BillCreate(provider="EKEDC", category="electricity", account_ref="ACC-1", verification=_bill_verified()), db=db
    )
    updated = lg.update_bill("u1", created["id"], BillPatch(last_paid="2026-01-01T00:00:00Z"), db=db)
    assert updated["last_paid"] is not None


# --------------------------------------------------------------- appointments --


def test_appointment_create_without_verification_is_rejected_by_schema():
    with pytest.raises(Exception):
        AppointmentCreate(provider="City General Hospital")


def test_appointment_provider_change_outside_enrollment_path_is_rejected(db):
    created = lg.create_appointment(
        "u1", AppointmentCreate(provider="City General Hospital", scheduled_for="Thursday 14th, 10:30am", verification=_appt_verified()), db=db
    )

    with pytest.raises(lg.TrustViolation):
        lg.update_appointment("u1", created["id"], AppointmentPatch(scheduled_for="Friday 15th, 9am"), db=db)

    unchanged = lg.get_appointment("u1", created["id"], db=db)
    assert unchanged["scheduled_for"] == "Thursday 14th, 10:30am"


def test_appointment_time_change_with_verification_is_allowed(db):
    created = lg.create_appointment(
        "u1", AppointmentCreate(provider="City General Hospital", scheduled_for="Thursday 14th, 10:30am", verification=_appt_verified()), db=db
    )
    updated = lg.update_appointment(
        "u1", created["id"], AppointmentPatch(scheduled_for="Friday 15th, 9am", verification=_appt_verified()), db=db
    )
    assert updated["scheduled_for"] == "Friday 15th, 9am"


def test_appointment_status_can_change_without_verification(db):
    created = lg.create_appointment(
        "u1", AppointmentCreate(provider="City General Hospital", verification=_appt_verified()), db=db
    )
    updated = lg.update_appointment("u1", created["id"], AppointmentPatch(status="confirmed"), db=db)
    assert updated["status"] == "confirmed"
