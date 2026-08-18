from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class PerceptionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str
    image_uri: str
    utterance: Optional[str] = None


class MedicationSummary(BaseModel):
    id: str
    name: str
    dose: Optional[str] = None
    condition: Optional[str] = None


class PerceptionResult(BaseModel):
    branch: Literal["confirm_identity", "ask_clarifying_question", "fallback_to_memory"]
    confidence: float = 0.0
    features_read: List[str] = Field(default_factory=list)
    matched_medication: Optional[MedicationSummary] = None
    ambiguous_medications: List[MedicationSummary] = Field(default_factory=list)


# what Gemini itself returns, before we've cross-checked med_ids against
# the user's actual known set


class GeminiCandidate(BaseModel):
    med_id: str
    confidence: float = Field(ge=0.0, le=1.0)


class GeminiMatch(BaseModel):
    candidates: List[GeminiCandidate] = Field(default_factory=list)
    features_read: List[str] = Field(default_factory=list)
