from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, model_validator


class AppointmentProposeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str
    appointment_id: str
    intent: Literal["confirm_attendance", "reschedule", "cancel"]
    new_time: Optional[str] = None

    @model_validator(mode="after")
    def _reschedule_needs_a_new_time(self) -> "AppointmentProposeRequest":
        if self.intent == "reschedule" and not self.new_time:
            raise ValueError("new_time is required when intent is 'reschedule'")
        return self


class AppointmentProposal(BaseModel):
    case_id: str
    appointment_id: str
    provider: str
    intent: Literal["confirm_attendance", "reschedule", "cancel"]
    read_back: str
    # no payment sits behind an appointment action, so there's no cap to
    # risk-scale against -- always "simple" here, kept on the response so
    # the frontend's one Proposed Action panel can treat every domain the
    # same way instead of appointments needing a special case.
    required_confirmation: Literal["simple"] = "simple"


class AppointmentConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str
    case_id: str
    confirmed: bool
    confirmed_by: str = "user"


class AppointmentResult(BaseModel):
    status: Literal["executed", "declined"]
    message: str
    confirmation_ref: Optional[str] = None
