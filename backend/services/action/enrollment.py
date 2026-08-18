"""Trusted-enrollment flows — the only place truth enters the Life Graph
for a med or a payment method. Every path here attaches a verification
block before calling the Memory Agent, so none of it is reachable from a
bare voice turn.
"""
from . import memory_client
from .gemini_extraction import extract_prescription_fields
from .paystack_client import PaystackError, get_paystack_client
from .pharmacy_client import PharmacyError, get_pharmacy_client
from .schemas import (
    MedicationExtractRequest,
    MedicationExtractResponse,
    MedicationImportRequest,
    MedicationVerifyRequest,
    PaymentEnrollRequest,
)


class EnrollmentError(RuntimeError):
    pass


class TrustedCircleNotVerified(EnrollmentError):
    pass


def extract_prescription(request: MedicationExtractRequest) -> MedicationExtractResponse:
    extraction = extract_prescription_fields(request.image_uri)
    document = memory_client.create_document(
        request.user_id,
        {
            "type": "prescription",
            "uri": request.image_uri,
            "extracted_fields": extraction.model_dump(exclude_none=True),
        },
    )
    return MedicationExtractResponse(document_id=document["id"], extracted=extraction)


def _require_trusted_circle_member(user_id: str, verified_by: str) -> None:
    people = memory_client.list_people(user_id)
    normalized = verified_by.strip().lower()
    for person in people:
        roles = [r.lower() for r in person.get("roles", [])]
        if person.get("name", "").strip().lower() == normalized and (
            "trusted_circle" in roles or "caregiver" in roles
        ):
            return
    raise TrustedCircleNotVerified(f"{verified_by!r} is not recorded as a trusted-circle member for this user")


def verify_and_enroll_medication(request: MedicationVerifyRequest) -> dict:
    if request.verification.method == "trusted_circle_verified":
        _require_trusted_circle_member(request.user_id, request.verification.verified_by)

    return memory_client.create_medication(
        request.user_id,
        {
            "name": request.name,
            "dose": request.dose,
            "condition": request.condition,
            "pharmacy_ref": request.pharmacy_ref,
            "cadence": request.cadence,
            "rx_ref": request.rx_ref,
            "verification": request.verification.model_dump(mode="json"),
        },
    )


def import_medication_from_dispensing_record(request: MedicationImportRequest) -> dict:
    pharmacy = get_pharmacy_client()
    try:
        record = pharmacy.get_dispensing_record(request.pharmacy_ref, request.dispensing_record_id)
    except PharmacyError as exc:
        raise EnrollmentError(str(exc)) from exc

    return memory_client.create_medication(
        request.user_id,
        {
            "name": record.name,
            "dose": record.dose,
            "condition": record.condition,
            "pharmacy_ref": record.pharmacy_ref,
            "cadence": record.cadence,
            "rx_ref": record.rx_ref,
            "verification": {
                "method": "dispensing_record_import",
                "verified_by": f"{record.pharmacy_ref} dispensing record {request.dispensing_record_id}",
                "rx_ref": record.rx_ref,
            },
        },
    )


def enroll_payment(request: PaymentEnrollRequest) -> dict:
    paystack = get_paystack_client()
    try:
        verified = paystack.verify_transaction(request.paystack_reference)
    except PaystackError as exc:
        raise EnrollmentError(str(exc)) from exc

    if verified.status != "success" or not verified.authorization_code:
        raise EnrollmentError(
            f"Paystack transaction {request.paystack_reference} did not complete (status={verified.status})"
        )

    return memory_client.write_payment(
        request.user_id,
        {
            "method_ref": verified.authorization_code,
            "per_transaction_cap": request.per_transaction_cap,
            "daily_cap": request.daily_cap,
            "never_auto_categories": request.never_auto_categories,
            "verification": {"method": "paystack_first_transaction_2fa"},
        },
    )
