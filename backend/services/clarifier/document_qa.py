"""Answers a question grounded only in the user's own retrieved documents
-- the RAG equivalent of "vision matches, never identifies": Gemini is
told explicitly to say it doesn't know rather than fill a gap from its
own general knowledge. A retrieval failure or a Gemini failure both fall
back to the same honest "couldn't check" message, never a guess.
"""
from typing import List, Tuple

from pydantic import BaseModel

from common.config import get_settings
from common.gcp_clients import get_genai_client
from common.logging_utils import get_logger

logger = get_logger("clarifier.document_qa")

NOTHING_ON_FILE = "I don't have anything in your documents about that."
COULD_NOT_CHECK = "I couldn't check your documents just now -- try again in a moment."


class GroundedAnswer(BaseModel):
    answer: str
    grounded_in_documents: bool


def answer_from_documents(question: str, matches: List[dict]) -> Tuple[str, bool]:
    if not matches:
        return NOTHING_ON_FILE, False

    try:
        return _answer_with_gemini(question, matches)
    except Exception:  # noqa: BLE001 - never guess if the grounded call itself fails
        logger.warning("document Q&A call failed, falling back to a plain message", exc_info=True)
        return COULD_NOT_CHECK, False


def _answer_with_gemini(question: str, matches: List[dict]) -> Tuple[str, bool]:
    settings = get_settings()
    client = get_genai_client()

    from google.genai import types

    excerpts = "\n\n".join(f"[{m['type']} document]\n{m['excerpt']}" for m in matches)
    prompt = (
        "Answer the question using ONLY the document excerpts below. If the excerpts "
        "don't actually answer it, say so plainly instead of guessing or using outside "
        "knowledge -- set grounded_in_documents to false in that case. Keep the answer "
        "short and plain-language.\n\n"
        f"Excerpts:\n{excerpts}\n\nQuestion: {question}"
    )

    response = client.models.generate_content(
        model=settings.gemini_pro_model,
        contents=[prompt],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=GroundedAnswer,
        ),
    )
    result = GroundedAnswer.model_validate_json(response.text)
    if not result.grounded_in_documents:
        return NOTHING_ON_FILE, False
    return result.answer, True
