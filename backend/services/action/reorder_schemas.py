from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict


class ReorderProposeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str
    med_id: str


class ReorderProposal(BaseModel):
    case_id: str
    med_id: str
    medication_name: str
    medication_dose: str
    pharmacy_ref: str
    amount_kobo: int
    payee: str
    card_description: str
    required_confirmation: Literal["simple", "step_up", "trusted_circle"]
    idempotency_key: str
    read_back: str


class ReorderConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str
    case_id: str
    confirmed: bool
    confirmed_by: str = "user"
    step_up_token: Optional[str] = None


class ReorderResult(BaseModel):
    status: Literal["executed", "declined", "aborted_duplicate", "requires_step_up", "requires_trusted_circle"]
    message: str
    order_id: Optional[str] = None
    charge_reference: Optional[str] = None
