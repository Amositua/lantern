from services.clarifier import clarifier, templates
from services.clarifier.schemas import (
    MedicationOption,
    MedicationQuestionRequest,
    PreferenceCorrectionRequest,
    ResolutionEventInput,
    ResolutionQuestionRequest,
    ResolveContradictionRequest,
)


def _no_profile(monkeypatch):
    monkeypatch.setattr(clarifier.memory_client, "get_life_graph", lambda user_id: {"profile": None})


def _no_gemini(monkeypatch):
    # phrase_question falls back to the raw template when Gemini isn't reachable --
    # keep tests deterministic by exercising that fallback path directly
    monkeypatch.setattr(clarifier, "phrase_question", lambda raw, profile: raw)


# ------------------------------------------------------- templates (pure) --


def test_classify_correction_scope_recognizes_one_off_phrasing():
    assert templates.classify_correction_scope("just this once, get the small pack") == "one_off"


def test_classify_correction_scope_recognizes_durable_phrasing():
    assert templates.classify_correction_scope("always get the small pack from now on") == "durable"


def test_classify_correction_scope_is_ambiguous_without_a_clear_cue():
    assert templates.classify_correction_scope("get the small pack") == "ambiguous"


# ------------------------------------------------- medication distinguishing --


def test_medication_question_is_a_single_plain_language_question(monkeypatch):
    _no_profile(monkeypatch)
    _no_gemini(monkeypatch)

    request = MedicationQuestionRequest(
        user_id="u1",
        candidates=[
            MedicationOption(id="med-amlo", name="Amlodipine", dose="10mg", condition="blood pressure"),
            MedicationOption(id="med-metf", name="Metformin", dose="500mg", condition="diabetes"),
        ],
    )
    result = clarifier.ask_medication_distinguishing_question(request)

    assert result.question.count("?") == 1
    assert "blood pressure" in result.question
    assert "diabetes" in result.question


# --------------------------------------------------- one-off vs durable --


def test_ambiguous_correction_asks_instead_of_writing(monkeypatch):
    _no_profile(monkeypatch)
    _no_gemini(monkeypatch)
    calls = []
    monkeypatch.setattr(clarifier.memory_client, "write_preference", lambda user_id, payload: calls.append(payload))

    request = PreferenceCorrectionRequest(
        user_id="u1", domain="pack_size", value="small", source_utterance="get the small pack"
    )
    result = clarifier.resolve_preference_correction(request)

    assert result.resolved is False
    assert result.question is not None
    assert calls == []


def test_explicit_one_off_utterance_writes_with_is_override_true(monkeypatch):
    _no_profile(monkeypatch)
    calls = []
    monkeypatch.setattr(
        clarifier.memory_client,
        "write_preference",
        lambda user_id, payload: calls.append(payload) or {"applied": True},
    )

    request = PreferenceCorrectionRequest(
        user_id="u1", domain="pack_size", value="large", source_utterance="just this once get the big one"
    )
    result = clarifier.resolve_preference_correction(request)

    assert result.resolved is True
    assert calls[0]["is_override"] is True
    assert calls[0]["source_utterance"] == "just this once get the big one"


def test_explicit_durable_utterance_writes_with_is_override_false(monkeypatch):
    _no_profile(monkeypatch)
    calls = []
    monkeypatch.setattr(
        clarifier.memory_client,
        "write_preference",
        lambda user_id, payload: calls.append(payload) or {"applied": True},
    )

    request = PreferenceCorrectionRequest(
        user_id="u1", domain="pack_size", value="small", source_utterance="always get the small pack from now on"
    )
    result = clarifier.resolve_preference_correction(request)

    assert result.resolved is True
    assert calls[0]["is_override"] is False


def test_resumed_answer_skips_classification_and_uses_the_given_scope(monkeypatch):
    _no_profile(monkeypatch)
    calls = []
    monkeypatch.setattr(
        clarifier.memory_client,
        "write_preference",
        lambda user_id, payload: calls.append(payload) or {"applied": True},
    )

    # utterance alone would be ambiguous, but the caller already resolved it
    # by asking the user directly (e.g. after test_ambiguous_correction_asks_instead_of_writing)
    request = PreferenceCorrectionRequest(
        user_id="u1", domain="pack_size", value="small", source_utterance="get the small pack", is_override=False
    )
    result = clarifier.resolve_preference_correction(request)

    assert result.resolved is True
    assert calls[0]["is_override"] is False


# ------------------------------------------------------- contradiction --


def test_resolution_question_mentions_both_the_existing_and_new_value(monkeypatch):
    _no_profile(monkeypatch)
    _no_gemini(monkeypatch)

    request = ResolutionQuestionRequest(
        user_id="u1",
        resolution_event=ResolutionEventInput(id="ev1", domain="pack_size", existing_value="small", new_value="large"),
    )
    result = clarifier.ask_resolution_question(request)

    assert result.question.count("?") == 1
    assert "small" in result.question
    assert "large" in result.question


def test_resolve_contradiction_calls_memory_agent_with_the_decision(monkeypatch):
    calls = []
    monkeypatch.setattr(
        clarifier.memory_client,
        "resolve_resolution_event",
        lambda user_id, event_id, payload: calls.append((user_id, event_id, payload)) or {"decision": payload["decision"]},
    )

    request = ResolveContradictionRequest(user_id="u1", event_id="ev1", decision="accept_new", resolved_by="user")
    result = clarifier.resolve_contradiction(request)

    assert result == {"decision": "accept_new"}
    assert calls == [("u1", "ev1", {"decision": "accept_new", "resolved_by": "user"})]
