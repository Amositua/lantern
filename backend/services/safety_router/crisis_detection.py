"""Deterministic crisis-phrase detection -- the safety net that has to
work even if Gemini is unreachable. Keyword-based on purpose: for this one
gate, predictable and testable beats nuanced. A missed crisis phrase is
far more costly than an unnecessary halt, so the phrase list stays fixed
and auditable rather than left to a probabilistic classifier.
"""
from typing import Literal, Optional

MEDICAL_EMERGENCY_PHRASES = (
    "chest pain",
    "can't breathe",
    "cannot breathe",
    "not breathing",
    "heart attack",
    "having a stroke",
    "seizure",
    "bleeding heavily",
    "unconscious",
    "overdose",
    "call an ambulance",
    "collapsed",
)

MENTAL_HEALTH_CRISIS_PHRASES = (
    "want to die",
    "kill myself",
    "end my life",
    "thinking about suicide",
    "suicidal",
    "hurt myself",
    "no reason to live",
    "better off dead",
    "can't go on",
)

CrisisType = Literal["medical_emergency", "mental_health_crisis"]


def detect_crisis_phrase(utterance: str) -> Optional[CrisisType]:
    text = utterance.lower()
    if any(phrase in text for phrase in MEDICAL_EMERGENCY_PHRASES):
        return "medical_emergency"
    if any(phrase in text for phrase in MENTAL_HEALTH_CRISIS_PHRASES):
        return "mental_health_crisis"
    return None
