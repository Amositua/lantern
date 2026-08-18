from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from .reorder_schemas import ReorderProposal


class ReengagementFireRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str
    med_id: str
    scheduled_at: Optional[datetime] = None


class ReengagementResult(BaseModel):
    status: Literal[
        "proposed",
        "aborted_rx_changed",
        "aborted_discontinued",
        "aborted_already_reordered",
        "deferred_quiet_hours",
        "escalated_to_trusted_circle",
    ]
    med_id: str
    message: str
    case_id: Optional[str] = None
    proposal: Optional[ReorderProposal] = None
    also_due: List[str] = Field(default_factory=list)
