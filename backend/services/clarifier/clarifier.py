"""Clarifier/Dialogue Agent -- owns three kinds of clarifying exchange:
which medication did they mean, is a correction one-off or durable, and
how to resolve a contradicted preference. Any exchange that resolves a
preference hands the Memory Agent the user's actual words as provenance.
"""
from typing import Optional

from common import memory_client

from . import templates
from .gemini_phrasing import phrase_question
from .schemas import (
    ClarifyingQuestion,
    MedicationQuestionRequest,
    PreferenceCorrectionRequest,
    PreferenceCorrectionResult,
    ResolutionQuestionRequest,
    ResolveContradictionRequest,
)


def _get_profile(user_id: str) -> Optional[dict]:
    try:
        life_graph = memory_client.get_life_graph(user_id)
    except memory_client.MemoryAgentError:
        return None
    return life_graph.get("profile")


def ask_medication_distinguishing_question(request: MedicationQuestionRequest) -> ClarifyingQuestion:
    raw = templates.medication_distinguishing_question(request.candidates)
    question = phrase_question(raw, _get_profile(request.user_id))
    return ClarifyingQuestion(question=question)


def resolve_preference_correction(request: PreferenceCorrectionRequest) -> PreferenceCorrectionResult:
    is_override = request.is_override
    if is_override is None:
        scope = templates.classify_correction_scope(request.source_utterance)
        if scope == "ambiguous":
            question = phrase_question(templates.one_off_vs_durable_question(), _get_profile(request.user_id))
            return PreferenceCorrectionResult(resolved=False, question=question)
        is_override = scope == "one_off"

    result = memory_client.write_preference(
        request.user_id,
        {
            "domain": request.domain,
            "value": request.value,
            "source_utterance": request.source_utterance,
            "is_override": is_override,
        },
    )
    return PreferenceCorrectionResult(resolved=True, result=result)


def ask_resolution_question(request: ResolutionQuestionRequest) -> ClarifyingQuestion:
    event = request.resolution_event
    raw = templates.contradiction_question(event.domain, event.existing_value, event.new_value)
    question = phrase_question(raw, _get_profile(request.user_id))
    return ClarifyingQuestion(question=question)


def resolve_contradiction(request: ResolveContradictionRequest) -> dict:
    return memory_client.resolve_resolution_event(
        request.user_id,
        request.event_id,
        {"decision": request.decision, "resolved_by": request.resolved_by},
    )
