from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class PrescriptionExtraction(BaseModel):
    name: Optional[str] = None
    dose: Optional[str] = None
    condition: Optional[str] = None
    rx_ref: Optional[str] = None
    prescribing_doctor: Optional[str] = None


class MedicationVerification(BaseModel):
    # has to match the Memory Agent's own MedicationVerification shape --
    # this is what we build here and Memory checks before writing
    model_config = ConfigDict(extra="forbid")

    method: Literal[
        "prescription_verified",
        "pharmacist_verified",
        "trusted_circle_verified",
        "dispensing_record_import",
    ]
    verified_by: str
    rx_ref: Optional[str] = None


class MedicationExtractRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str
    image_uri: str


class MedicationExtractResponse(BaseModel):
    document_id: str
    extracted: PrescriptionExtraction


class MedicationVerifyRequest(BaseModel):
    # human-confirmed fields, either after reviewing an extraction or
    # entered directly for a manual/trusted-circle enrollment
    model_config = ConfigDict(extra="forbid")

    user_id: str
    name: str
    dose: str
    condition: Optional[str] = None
    pharmacy_ref: Optional[str] = None
    cadence: Optional[int] = None
    rx_ref: Optional[str] = None
    verification: MedicationVerification


class MedicationImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str
    pharmacy_ref: str
    dispensing_record_id: str


class PaymentEnrollRequest(BaseModel):
    # no card fields on purpose -- just the Paystack reference, verified
    # server-side before this ever reaches the Life Graph
    model_config = ConfigDict(extra="forbid")

    user_id: str
    paystack_reference: str
    per_transaction_cap: float = Field(..., gt=0)
    daily_cap: float = Field(..., gt=0)
    never_auto_categories: List[str] = Field(default_factory=list)


class DocumentImportRequest(BaseModel):
    # letters/labels -- reference material, not a Life Graph identity fact,
    # so unlike the medication paths above this needs no verification block
    model_config = ConfigDict(extra="forbid")

    user_id: str
    image_uri: str
    doc_type: Literal["letter", "label", "other"] = "letter"


class DocumentImportResponse(BaseModel):
    document_id: str
    doc_type: str
    text: str
