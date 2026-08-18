from services.perception import perception
from services.perception.schemas import GeminiCandidate, GeminiMatch, PerceptionRequest

AMLODIPINE = {"id": "med-amlo", "name": "Amlodipine", "dose": "10mg", "condition": "blood pressure"}
METFORMIN = {"id": "med-metf", "name": "Metformin", "dose": "500mg", "condition": "diabetes"}


def _request(monkeypatch, known_meds, gemini_match, utterance="I'm running low on this"):
    monkeypatch.setattr(perception.memory_client, "list_medications", lambda user_id: known_meds)
    monkeypatch.setattr(perception, "match_against_known_meds", lambda image_uri, u, meds: gemini_match)
    return perception.perceive(PerceptionRequest(user_id="u1", image_uri="gs://demo/frame.jpg", utterance=utterance))


def test_known_med_high_confidence_routes_to_the_right_life_graph_entry(monkeypatch):
    gemini_match = GeminiMatch(
        candidates=[GeminiCandidate(med_id="med-amlo", confidence=0.9)],
        features_read=["partial text: AMLO", "white round tablet"],
    )
    result = _request(monkeypatch, [AMLODIPINE, METFORMIN], gemini_match)

    assert result.branch == "confirm_identity"
    assert result.matched_medication.id == "med-amlo"
    assert result.matched_medication.name == "Amlodipine"
    assert result.confidence == 0.9


def test_lookalike_triggers_clarifying_question_not_a_guess(monkeypatch):
    gemini_match = GeminiMatch(
        candidates=[
            GeminiCandidate(med_id="med-amlo", confidence=0.5),
            GeminiCandidate(med_id="med-metf", confidence=0.45),
        ],
        features_read=["white round tablet, no legible text"],
    )
    result = _request(monkeypatch, [AMLODIPINE, METFORMIN], gemini_match)

    assert result.branch == "ask_clarifying_question"
    assert result.matched_medication is None
    matched_ids = {m.id for m in result.ambiguous_medications}
    assert matched_ids == {"med-amlo", "med-metf"}


def test_unreadable_falls_back_to_memory_not_a_fabricated_identity(monkeypatch):
    gemini_match = GeminiMatch(candidates=[], features_read=[])
    result = _request(monkeypatch, [AMLODIPINE, METFORMIN], gemini_match)

    assert result.branch == "fallback_to_memory"
    assert result.matched_medication is None
    assert result.ambiguous_medications == []


def test_single_candidate_below_high_confidence_falls_back_rather_than_confirming(monkeypatch):
    gemini_match = GeminiMatch(candidates=[GeminiCandidate(med_id="med-amlo", confidence=0.5)], features_read=["blurry label"])
    result = _request(monkeypatch, [AMLODIPINE, METFORMIN], gemini_match)

    assert result.branch == "fallback_to_memory"
    assert result.confidence == 0.5


def test_hallucinated_med_id_outside_the_users_known_set_is_dropped(monkeypatch):
    # Gemini invents a drug identity that isn't in this user's Life Graph --
    # must never be trusted, no matter how confident it claims to be.
    gemini_match = GeminiMatch(
        candidates=[GeminiCandidate(med_id="not-a-real-med-id", confidence=0.99)],
        features_read=["a drug name Gemini recognized on its own"],
    )
    result = _request(monkeypatch, [AMLODIPINE, METFORMIN], gemini_match)

    assert result.branch == "fallback_to_memory"
    assert result.matched_medication is None


def test_no_known_medications_falls_back_without_calling_gemini(monkeypatch):
    monkeypatch.setattr(perception.memory_client, "list_medications", lambda user_id: [])

    def _should_not_be_called(*args, **kwargs):
        raise AssertionError("should not call Gemini when the user has no known meds")

    monkeypatch.setattr(perception, "match_against_known_meds", _should_not_be_called)

    result = perception.perceive(PerceptionRequest(user_id="u1", image_uri="gs://demo/frame.jpg"))
    assert result.branch == "fallback_to_memory"
