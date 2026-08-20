from typing import Any, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class MedicationOption(BaseModel):
    id: str
    name: str
    dose: Optional[str] = None
    condition: Optional[str] = None


class MedicationQuestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str
    candidates: List[MedicationOption] = Field(..., min_length=2)


class ClarifyingQuestion(BaseModel):
    question: str


class PreferenceCorrectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str
    domain: str
    value: Any
    source_utterance: str
    is_override: Optional[bool] = None


class PreferenceCorrectionResult(BaseModel):
    resolved: bool
    question: Optional[str] = None
    result: Optional[dict] = None


class ResolutionEventInput(BaseModel):
    id: str
    domain: str
    existing_value: Any
    new_value: Any


class ResolutionQuestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str
    resolution_event: ResolutionEventInput


class ResolveContradictionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str
    event_id: str
    decision: Literal["accept_new", "keep_existing"]
    resolved_by: str


class DocumentQuestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str
    question: str


class DocumentSource(BaseModel):
    document_id: str
    type: Optional[str] = None
    uri: Optional[str] = None


class DocumentAnswer(BaseModel):
    answer: str
    grounded: bool
    sources: List[DocumentSource] = Field(default_factory=list)
