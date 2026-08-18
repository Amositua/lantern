"""Gemini Pro phrasing of a clarifying question, adapted to the user's
pacing/literacy profile. Falls back to the plain template on any failure --
asking is the safe path and can't depend on this call succeeding.
"""
from typing import Optional

from pydantic import BaseModel

from common.config import get_settings
from common.gcp_clients import get_genai_client
from common.logging_utils import get_logger

logger = get_logger("clarifier.gemini_phrasing")


class PhrasedQuestion(BaseModel):
    question: str


def phrase_question(raw_intent: str, profile: Optional[dict]) -> str:
    try:
        return _phrase_with_gemini(raw_intent, profile)
    except Exception:  # noqa: BLE001 - a phrasing failure must not block asking the question at all
        logger.warning("falling back to the plain template, Gemini phrasing failed", exc_info=True)
        return raw_intent


def _phrase_with_gemini(raw_intent: str, profile: Optional[dict]) -> str:
    settings = get_settings()
    client = get_genai_client()

    from google.genai import types

    profile = profile or {}
    style_notes = []
    if profile.get("pacing_pref"):
        style_notes.append(f"pacing preference: {profile['pacing_pref']}")
    if profile.get("literacy_level"):
        style_notes.append(f"literacy level: {profile['literacy_level']}")
    abilities = profile.get("abilities") or {}
    if abilities.get("jargon_averse"):
        style_notes.append("avoid jargon, use plain everyday words")
    if abilities.get("speaks_slowly"):
        style_notes.append("keep it to one short sentence")

    style = "; ".join(style_notes) or "no profile on file, keep it plain and short"

    prompt = (
        "Rephrase this so it reads as one short, plain-language question a calm "
        f"assistant would actually say out loud. Style notes: {style}. Ask exactly "
        f"one question, nothing else.\n\nQuestion to rephrase: {raw_intent}"
    )

    response = client.models.generate_content(
        model=settings.gemini_pro_model,
        contents=[prompt],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=PhrasedQuestion,
        ),
    )
    return PhrasedQuestion.model_validate_json(response.text).question
