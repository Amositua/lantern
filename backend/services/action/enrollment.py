"""Trusted-enrollment flows — the only place truth enters the Life Graph
for a med or a payment method. Every path here attaches a verification
block before calling the Memory Agent, so none of it is reachable from a
bare voice turn.
"""
from typing import Optional

from common import memory_client

from .gemini_extraction import extract_prescription_fields, transcribe_document
from .paystack_client import PaystackError, get_paystack_client
from .pharmacy_client import PharmacyError, get_pharmacy_client
from .schemas import (
    DocumentImportRequest,
    DocumentImportResponse,
    MedicationExtractRequest,
    MedicationExtractResponse,
    MedicationImportRequest,
    MedicationVerifyRequest,
    PaymentEnrollRequest,
)
from .trust_checks import TrustedCircleNotVerified, require_trusted_circle_member

__all__ = ["EnrollmentError", "TrustedCircleNotVerified"]


class EnrollmentError(RuntimeError):
    pass


def _prescription_summary(extraction) -> Optional[str]:
    if not extraction.name:
        return None
    parts = [extraction.name]
    if extraction.dose:
        parts.append(extraction.dose)
    summary = " ".join(parts)
    if extraction.condition:
        summary += f", for {extraction.condition}"
    if extraction.rx_ref:
        summary += f", ref {extraction.rx_ref}"
    if extraction.prescribing_doctor:
        summary += f", prescribed by {extraction.prescribing_doctor}"
    return summary


def extract_prescription(request: MedicationExtractRequest) -> MedicationExtractResponse:
    extraction = extract_prescription_fields(request.image_uri)
    document = memory_client.create_document(
        request.user_id,
        {
            "type": "prescription",
            "uri": request.image_uri,
            "extracted_fields": extraction.model_dump(exclude_none=True),
            "text": _prescription_summary(extraction),
        },
    )
    return MedicationExtractResponse(document_id=document["id"], extracted=extraction)


def import_reference_document(request: DocumentImportRequest) -> DocumentImportResponse:
    """Letters and labels -- read, stored, and made searchable, but never
    written into the Life Graph as a fact. This is what backs 'what did
    that letter say', not a trust-tiered enrollment path."""
    text = transcribe_document(request.image_uri, request.doc_type)
    document = memory_client.create_document(
        request.user_id,
        {"type": request.doc_type, "uri": request.image_uri, "text": text},
    )
    return DocumentImportResponse(document_id=document["id"], doc_type=request.doc_type, text=text)


def verify_and_enroll_medication(request: MedicationVerifyRequest) -> dict:
    if request.verification.method == "trusted_circle_verified":
        require_trusted_circle_member(request.user_id, request.verification.verified_by)

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
            "card_last4": verified.last4,
            "card_bank": verified.bank,
            "per_transaction_cap": request.per_transaction_cap,
            "daily_cap": request.daily_cap,
            "never_auto_categories": request.never_auto_categories,
            "verification": {"method": "paystack_first_transaction_2fa"},
        },
    )
