import pytest

from services.action import enrollment
from services.action.paystack_client import SandboxPaystackClient
from services.action.pharmacy_client import SandboxPharmacyClient
from services.action.schemas import (
    MedicationImportRequest,
    MedicationVerification,
    MedicationVerifyRequest,
    PaymentEnrollRequest,
)


def test_payment_enroll_request_rejects_raw_card_fields():
    with pytest.raises(Exception):
        PaymentEnrollRequest(
            user_id="u1",
            paystack_reference="demo_success_1",
            per_transaction_cap=10000,
            daily_cap=20000,
            card_number="4111111111111111",
        )


# ------------------------------------------------------- trusted circle --


def test_trusted_circle_verification_requires_membership(monkeypatch):
    monkeypatch.setattr(enrollment.memory_client, "list_people", lambda user_id: [])
    calls = []
    monkeypatch.setattr(enrollment.memory_client, "create_medication", lambda user_id, payload: calls.append(payload))

    request = MedicationVerifyRequest(
        user_id="u1",
        name="Amlodipine",
        dose="10mg",
        verification=MedicationVerification(method="trusted_circle_verified", verified_by="Aunty Bisi"),
    )

    with pytest.raises(enrollment.TrustedCircleNotVerified):
        enrollment.verify_and_enroll_medication(request)

    assert calls == []


def test_trusted_circle_verification_succeeds_for_a_recorded_member(monkeypatch):
    monkeypatch.setattr(
        enrollment.memory_client,
        "list_people",
        lambda user_id: [{"name": "Aunty Bisi", "roles": ["trusted_circle"]}],
    )
    calls = []
    monkeypatch.setattr(
        enrollment.memory_client,
        "create_medication",
        lambda user_id, payload: calls.append(payload) or {"id": "med1", **payload},
    )

    request = MedicationVerifyRequest(
        user_id="u1",
        name="Amlodipine",
        dose="10mg",
        verification=MedicationVerification(method="trusted_circle_verified", verified_by="Aunty Bisi"),
    )
    result = enrollment.verify_and_enroll_medication(request)

    assert len(calls) == 1
    assert result["verification"]["method"] == "trusted_circle_verified"


# ------------------------------------------------------ dispensing import --


def test_dispensing_record_import_carries_pharmacy_verification(monkeypatch):
    monkeypatch.setattr(enrollment, "get_pharmacy_client", lambda: SandboxPharmacyClient())
    calls = []
    monkeypatch.setattr(
        enrollment.memory_client,
        "create_medication",
        lambda user_id, payload: calls.append(payload) or {"id": "med1", **payload},
    )

    request = MedicationImportRequest(user_id="u1", pharmacy_ref="pharmarun_demo", dispensing_record_id="DR-1001")
    result = enrollment.import_medication_from_dispensing_record(request)

    assert result["name"] == "Amlodipine"
    assert calls[0]["verification"]["method"] == "dispensing_record_import"


def test_dispensing_record_not_found_raises_enrollment_error(monkeypatch):
    monkeypatch.setattr(enrollment, "get_pharmacy_client", lambda: SandboxPharmacyClient())
    monkeypatch.setattr(enrollment.memory_client, "create_medication", lambda user_id, payload: pytest.fail("should not write"))

    request = MedicationImportRequest(user_id="u1", pharmacy_ref="pharmarun_demo", dispensing_record_id="DR-9999")
    with pytest.raises(enrollment.EnrollmentError):
        enrollment.import_medication_from_dispensing_record(request)


# ------------------------------------------------------- payment enrollment --


def test_payment_enrollment_rejects_a_failed_transaction(monkeypatch):
    monkeypatch.setattr(enrollment, "get_paystack_client", lambda: SandboxPaystackClient())
    monkeypatch.setattr(enrollment.memory_client, "write_payment", lambda user_id, payload: pytest.fail("should not write"))

    request = PaymentEnrollRequest(
        user_id="u1", paystack_reference="demo_fail_1", per_transaction_cap=10000, daily_cap=20000
    )
    with pytest.raises(enrollment.EnrollmentError):
        enrollment.enroll_payment(request)


def test_payment_enrollment_stores_only_the_token_with_caps(monkeypatch):
    monkeypatch.setattr(enrollment, "get_paystack_client", lambda: SandboxPaystackClient())
    calls = []
    monkeypatch.setattr(
        enrollment.memory_client,
        "write_payment",
        lambda user_id, payload: calls.append(payload) or payload,
    )

    request = PaymentEnrollRequest(
        user_id="u1",
        paystack_reference="demo_success_1",
        per_transaction_cap=10000,
        daily_cap=20000,
        never_auto_categories=["medical_procedure"],
    )
    result = enrollment.enroll_payment(request)

    assert result["method_ref"].startswith("AUTH_")
    assert result["per_transaction_cap"] == 10000
    assert result["daily_cap"] == 20000
    assert result["never_auto_categories"] == ["medical_procedure"]
    assert result["verification"]["method"] == "paystack_first_transaction_2fa"

    forbidden_keys = {"card_number", "cvv", "pan", "expiry", "card"}
    assert forbidden_keys.isdisjoint(calls[0].keys())
