"""Vision matches against the user's known meds, never identifies one from
scratch. Whatever Gemini returns gets cross-checked against this user's
actual Life Graph med set before any of it reaches a caller -- a med_id
that isn't on record gets dropped, not trusted.
"""
from typing import List

from common import memory_client

from .gemini_match import match_against_known_meds
from .schemas import GeminiCandidate, MedicationSummary, PerceptionRequest, PerceptionResult

HIGH_CONFIDENCE_THRESHOLD = 0.75


def perceive(request: PerceptionRequest) -> PerceptionResult:
    known_meds = memory_client.list_medications(request.user_id)
    known_by_id = {m["id"]: m for m in known_meds}

    if not known_meds:
        return PerceptionResult(branch="fallback_to_memory")

    raw = match_against_known_meds(request.image_uri, request.utterance, known_meds)
    candidates = _valid_candidates(raw.candidates, known_by_id)

    if len(candidates) == 1 and candidates[0].confidence >= HIGH_CONFIDENCE_THRESHOLD:
        top = candidates[0]
        return PerceptionResult(
            branch="confirm_identity",
            confidence=top.confidence,
            features_read=raw.features_read,
            matched_medication=_summarize(known_by_id[top.med_id]),
        )

    if len(candidates) >= 2:
        return PerceptionResult(
            branch="ask_clarifying_question",
            confidence=candidates[0].confidence,
            features_read=raw.features_read,
            ambiguous_medications=[_summarize(known_by_id[c.med_id]) for c in candidates],
        )

    # zero candidates, or one candidate that isn't confident enough -- same
    # bucket as "nothing readable": fall back to memory, don't guess
    return PerceptionResult(
        branch="fallback_to_memory",
        confidence=candidates[0].confidence if candidates else 0.0,
        features_read=raw.features_read,
    )


def _valid_candidates(candidates: List[GeminiCandidate], known_by_id: dict) -> List[GeminiCandidate]:
    valid = [c for c in candidates if c.med_id in known_by_id]
    return sorted(valid, key=lambda c: c.confidence, reverse=True)


def _summarize(med: dict) -> MedicationSummary:
    return MedicationSummary(id=med["id"], name=med["name"], dose=med.get("dose"), condition=med.get("condition"))
