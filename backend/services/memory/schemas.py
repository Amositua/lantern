from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class ProfileWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = None
    language: Optional[str] = None
    literacy_level: Optional[str] = None
    abilities: Optional[Dict[str, bool]] = None
    pacing_pref: Optional[str] = None
    quiet_hours_start: Optional[int] = Field(None, ge=0, le=23)
    quiet_hours_end: Optional[int] = Field(None, ge=0, le=23)


class MedicationVerification(BaseModel):
    # we can only check this block is present/well-formed, not that the
    # verification actually happened -- that's on the enrollment flow calling us

    model_config = ConfigDict(extra="forbid")

    method: Literal[
        "prescription_verified",
        "pharmacist_verified",
        "trusted_circle_verified",
        "dispensing_record_import",
    ]
    verified_by: str
    rx_ref: Optional[str] = None
    verified_at: Optional[datetime] = None


class MedicationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    dose: str
    condition: Optional[str] = None
    pharmacy_ref: Optional[str] = None
    cadence: Optional[int] = None
    rx_ref: Optional[str] = None
    verification: MedicationVerification


class MedicationPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = None
    dose: Optional[str] = None
    condition: Optional[str] = None
    pharmacy_ref: Optional[str] = None
    cadence: Optional[int] = None
    rx_ref: Optional[str] = None
    last_refill: Optional[datetime] = None
    discontinued: Optional[bool] = None
    verification: Optional[MedicationVerification] = None


class AppointmentVerification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: Literal["document_import", "clinic_verified", "trusted_circle_verified"]
    verified_by: str
    verified_at: Optional[datetime] = None


class AppointmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    purpose: Optional[str] = None
    scheduled_for: Optional[str] = None  # free-text on purpose -- a letter says "Thursday the 14th at 10:30am", not an ISO timestamp
    location: Optional[str] = None
    source_document_id: Optional[str] = None
    verification: AppointmentVerification


class AppointmentPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Optional[str] = None
    scheduled_for: Optional[str] = None
    location: Optional[str] = None
    status: Optional[str] = None
    cancelled: Optional[bool] = None
    verification: Optional[AppointmentVerification] = None


class PersonWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    relation: Optional[str] = None
    roles: List[str] = Field(default_factory=list)
    contact: Optional[str] = None


class PaymentVerification(BaseModel):
    # same deal as MedicationVerification -- checks presence, not that the
    # OTP/PIN/3DS challenge really happened

    model_config = ConfigDict(extra="forbid")

    method: Literal["paystack_first_transaction_2fa"]
    verified_at: Optional[datetime] = None


class PaymentWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method_ref: str = Field(..., min_length=1, description="Paystack authorization_code — a token, never a card number")
    card_last4: Optional[str] = Field(None, description="Last 4 digits only, for read-back — never the full PAN")
    card_bank: Optional[str] = None
    per_transaction_cap: Optional[float] = None
    daily_cap: Optional[float] = None
    never_auto_categories: List[str] = Field(default_factory=list)
    verification: PaymentVerification


class DocumentWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    uri: str
    extracted_fields: Dict[str, Any] = Field(default_factory=dict)
    text: Optional[str] = Field(
        None, description="Plain-text content to make this document searchable via RAG. Omit for no embedding."
    )


class PreferenceWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: str
    value: Any
    source_utterance: str
    is_override: bool = Field(
        ..., description="True = just this once (never becomes the standing belief). False = durable."
    )


class CaseWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: str
    state: str
    steps: List[str] = Field(default_factory=list)
    pending_async_ref: Optional[str] = None
    data: Dict[str, Any] = Field(default_factory=dict, description="Task-specific payload, e.g. a reorder proposal")


class CasePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: Optional[str] = None
    steps: Optional[List[str]] = None
    pending_async_ref: Optional[str] = None
    data: Optional[Dict[str, Any]] = None


class AuditWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str
    proposed: Dict[str, Any] = Field(default_factory=dict)
    confirmed_by: Optional[str] = None
    method: Optional[str] = None
    result: Optional[str] = None
    idempotency_key: Optional[str] = None


class ResolutionEventResolve(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["accept_new", "keep_existing"]
    resolved_by: str
