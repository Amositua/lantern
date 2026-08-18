"""Deterministic fallbacks -- a clarifying question can always be asked
even if Gemini's down, since asking is the safe behavior and shouldn't
depend on an external call succeeding.
"""
from typing import List, Literal

from .schemas import MedicationOption

ONE_OFF_PHRASES = ("just this once", "just this time", "only this time", "only today", "this one time")
DURABLE_PHRASES = ("always", "from now on", "every time", "from here on", "going forward")


def classify_correction_scope(utterance: str) -> Literal["one_off", "durable", "ambiguous"]:
    text = utterance.lower()
    if any(phrase in text for phrase in ONE_OFF_PHRASES):
        return "one_off"
    if any(phrase in text for phrase in DURABLE_PHRASES):
        return "durable"
    return "ambiguous"


def one_off_vs_durable_question() -> str:
    return "Just this once, or should I always do it this way from now on?"


def medication_distinguishing_question(candidates: List[MedicationOption]) -> str:
    conditions = [c.condition for c in candidates if c.condition]
    if len(conditions) == len(candidates) and len(set(conditions)) == len(candidates):
        options = " or ".join(f"the one for your {c.condition}" for c in candidates)
        return f"Which one do you mean -- {options}?"

    doses = [c.dose for c in candidates if c.dose]
    if len(doses) == len(candidates) and len(set(doses)) == len(candidates):
        options = " or ".join(f"the {c.dose} one" for c in candidates)
        return f"Which one do you mean -- {options}?"

    options = " or ".join(c.name for c in candidates)
    return f"Which one do you mean -- {options}?"


def contradiction_question(domain: str, existing_value: object, new_value: object) -> str:
    topic = domain.replace("_", " ")
    return (
        f"You told me before it was usually {existing_value} for {topic}, but just now it "
        f"sounded like {new_value} -- which should I go with?"
    )
