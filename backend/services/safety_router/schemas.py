from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict


class SafetyCheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str
    utterance: Optional[str] = None
    confidence: Optional[float] = None
    case_id: Optional[str] = None  # an in-progress case to veto if this turn halts


class HandoffContact(BaseModel):
    name: Optional[str] = None
    relation: Optional[str] = None
    contact: Optional[str] = None
    source: Literal["trusted_circle_emergency_contact", "crisis_hotline", "national_emergency_number"]


class SafetyCheckResult(BaseModel):
    verdict: Literal["proceed", "halt"]
    trigger: Optional[Literal["crisis_phrase", "low_confidence"]] = None
    reason: Optional[str] = None
    handoff: Optional[HandoffContact] = None
    vetoed_case_id: Optional[str] = None
