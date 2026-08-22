from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict


class BillProposeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str
    bill_id: str


class BillProposal(BaseModel):
    case_id: str
    bill_id: str
    provider: str
    category: str
    account_ref: str
    amount_kobo: int
    card_description: str
    required_confirmation: Literal["simple", "step_up", "trusted_circle"]
    idempotency_key: str
    read_back: str


class BillConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str
    case_id: str
    confirmed: bool
    confirmed_by: str = "user"
    step_up_token: Optional[str] = None


class BillResult(BaseModel):
    status: Literal["executed", "declined", "aborted_already_paid", "requires_step_up", "requires_trusted_circle"]
    message: str
    payment_reference: Optional[str] = None
