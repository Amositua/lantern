import pytest

from services.action import enrollment
from services.action.paystack_client import SandboxPaystackClient
from services.action.pharmacy_client import SandboxPharmacyClient
from services.action.schemas import (
    DocumentImportRequest,
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


def test_enrolling_with_the_demo_timeout_reference_produces_a_token_that_times_out_once(monkeypatch):
    # this is what the demo's no-double-charge script enrolls with, on purpose,
    # to prove verify-before-retry live rather than only in a unit test
    paystack = SandboxPaystackClient()
    monkeypatch.setattr(enrollment, "get_paystack_client", lambda: paystack)
    monkeypatch.setattr(enrollment.memory_client, "write_payment", lambda user_id, payload: payload)

    request = PaymentEnrollRequest(
        user_id="u1", paystack_reference="demo_timeout_setup_1", per_transaction_cap=10000, daily_cap=20000
    )
    result = enrollment.enroll_payment(request)
    method_ref = result["method_ref"]

    assert method_ref.startswith("AUTH_timeout_once_")

    # the very next charge against this token times out once, then succeeds
    from services.action.paystack_client import PaystackTimeoutError

    with pytest.raises(PaystackTimeoutError):
        paystack.charge_authorization(method_ref, 450000, "user+u1@lantern.local", "idem-1")
    charge = paystack.charge_authorization(method_ref, 450000, "user+u1@lantern.local", "idem-1")
    assert charge.status == "success"
    assert len(paystack._charges) == 1  # one idempotency key, one recorded charge, despite two calls


# --------------------------------------------------------- document import --


def test_importing_a_letter_stores_the_transcription_as_searchable_text(monkeypatch):
    monkeypatch.setattr(enrollment, "transcribe_document", lambda uri, doc_type: "Your appointment is on the 14th.")
    calls = []
    monkeypatch.setattr(
        enrollment.memory_client,
        "create_document",
        lambda user_id, payload: calls.append(payload) or {"id": "doc-1"},
    )

    request = DocumentImportRequest(user_id="u1", image_uri="gs://x/letter.jpg", doc_type="letter")
    result = enrollment.import_reference_document(request)

    assert result.document_id == "doc-1"
    assert result.text == "Your appointment is on the 14th."
    assert calls[0]["text"] == "Your appointment is on the 14th."
    assert calls[0]["type"] == "letter"
    assert "verification" not in calls[0]  # reference material, not a Life Graph fact


def test_document_import_request_rejects_an_unrecognized_doc_type():
    with pytest.raises(Exception):
        DocumentImportRequest(user_id="u1", image_uri="gs://x/y.jpg", doc_type="something_else")
