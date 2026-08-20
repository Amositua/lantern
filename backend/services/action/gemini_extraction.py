"""Gemini Pro extraction for the prescription enrollment path.

Doesn't touch the Life Graph itself — just proposes fields for a human to
confirm in enrollment.verify_and_enroll_medication. Misread prescription =
bad proposal, not a bad fact.
"""
from common.config import get_settings
from common.gcp_clients import get_genai_client

from .schemas import PrescriptionExtraction


def extract_prescription_fields(image_uri: str) -> PrescriptionExtraction:
    settings = get_settings()
    client = get_genai_client()

    from google.genai import types

    response = client.models.generate_content(
        model=settings.gemini_pro_model,
        contents=[
            types.Part.from_uri(file_uri=image_uri, mime_type="image/jpeg"),
            (
                "Read this prescription image and extract the medication name, dose, "
                "the condition it treats, the prescription reference number, and the "
                "prescribing doctor's name. Leave a field blank rather than guessing "
                "if it isn't legible."
            ),
        ],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=PrescriptionExtraction,
        ),
    )
    return PrescriptionExtraction.model_validate_json(response.text)


def transcribe_document(image_uri: str, doc_type: str) -> str:
    """Plain-text transcription of a letter/label image -- what makes it
    searchable later, not a structured extraction like the prescription
    path above. No Life Graph identity is at stake here, so there's no
    verification gate: this is reference material, not a fact Lantern acts on.
    """
    settings = get_settings()
    client = get_genai_client()

    from google.genai import types

    response = client.models.generate_content(
        model=settings.gemini_pro_model,
        contents=[
            types.Part.from_uri(file_uri=image_uri, mime_type="image/jpeg"),
            f"Transcribe this {doc_type} image in full, plain text. Include every date, "
            "name, and instruction exactly as written. Don't summarize or omit anything.",
        ],
    )
    return response.text
