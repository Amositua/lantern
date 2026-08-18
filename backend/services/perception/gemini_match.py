"""Gemini Flash visual matching against a short, explicit list of the
user's own known medications. Never asked to identify a drug from
scratch -- only to pick among options we hand it, or say it can't tell.
"""
from typing import List, Optional

from common.config import get_settings
from common.gcp_clients import get_genai_client

from .schemas import GeminiMatch


def match_against_known_meds(image_uri: str, utterance: Optional[str], known_meds: List[dict]) -> GeminiMatch:
    settings = get_settings()
    client = get_genai_client()

    from google.genai import types

    med_lines = "\n".join(
        f"- id={m['id']}: {m['name']} {m.get('dose') or ''} ({m.get('condition') or 'no condition on file'})"
        for m in known_meds
    )

    prompt = (
        "This user takes only the following medications -- do not suggest "
        "anything outside this list, and do not name a drug that isn't on "
        "it even if you recognize it from the image:\n"
        f"{med_lines}\n\n"
        f"They said: {utterance or '(no utterance)'}\n\n"
        "Look at the image and decide which of the medications above it "
        "most likely is, based on visible label text, packaging, or "
        "appearance. List every plausible match with a confidence from 0 "
        "to 1 -- if two could be it, list both rather than guessing one. "
        "If nothing is legible or nothing matches, return no candidates "
        "rather than a low-confidence guess. Note what you actually saw "
        "(partial text, color, shape, packaging) in features_read."
    )

    response = client.models.generate_content(
        model=settings.gemini_flash_model,
        contents=[types.Part.from_uri(file_uri=image_uri, mime_type="image/jpeg"), prompt],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=GeminiMatch,
        ),
    )
    return GeminiMatch.model_validate_json(response.text)
