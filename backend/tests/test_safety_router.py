import pytest

from services.action import reorder
from services.action.reorder_schemas import ReorderConfirmRequest, ReorderProposeRequest
from services.safety_router import safety_router
from services.safety_router.schemas import SafetyCheckRequest

from .memory_fakes import FakeMemoryStore

AMLODIPINE = {
    "id": "med-amlo",
    "name": "Amlodipine",
    "dose": "10mg",
    "condition": "blood pressure",
    "pharmacy_ref": "pharmarun_demo",
    "cadence": 30,
    "last_refill": None,
}

PAYMENT = {
    "method_ref": "AUTH_sandbox_abc",
    "card_last4": "4242",
    "per_transaction_cap": 10000.0,
    "daily_cap": 20000.0,
    "never_auto_categories": [],
}


def _wire(monkeypatch, store):
    monkeypatch.setattr(safety_router.memory_client, "list_people", store.list_people)
    monkeypatch.setattr(safety_router.memory_client, "get_case", store.get_case)
    monkeypatch.setattr(safety_router.memory_client, "update_case", store.update_case)
    monkeypatch.setattr(safety_router.memory_client, "append_audit", store.append_audit)


# -------------------------------------------------------------- crisis phrase --


def test_medical_emergency_phrase_halts_with_a_handoff(monkeypatch):
    store = FakeMemoryStore()
    _wire(monkeypatch, store)

    result = safety_router.check_turn(SafetyCheckRequest(user_id="u1", utterance="I have chest pain and can't breathe"))

    assert result.verdict == "halt"
    assert result.trigger == "crisis_phrase"
    assert result.handoff is not None


def test_mental_health_crisis_phrase_halts(monkeypatch):
    store = FakeMemoryStore()
    _wire(monkeypatch, store)

    result = safety_router.check_turn(SafetyCheckRequest(user_id="u1", utterance="I just want to end my life"))

    assert result.verdict == "halt"
    assert result.trigger == "crisis_phrase"


def test_ordinary_utterance_proceeds(monkeypatch):
    store = FakeMemoryStore()
    _wire(monkeypatch, store)

    result = safety_router.check_turn(SafetyCheckRequest(user_id="u1", utterance="I'm running low on my blood pressure pills"))

    assert result.verdict == "proceed"
    assert result.trigger is None


# ------------------------------------------------------------- low confidence --


def test_low_confidence_halts_even_without_an_utterance(monkeypatch):
    store = FakeMemoryStore()
    _wire(monkeypatch, store)

    result = safety_router.check_turn(SafetyCheckRequest(user_id="u1", confidence=0.2))

    assert result.verdict == "halt"
    assert result.trigger == "low_confidence"


def test_adequate_confidence_proceeds(monkeypatch):
    store = FakeMemoryStore()
    _wire(monkeypatch, store)

    result = safety_router.check_turn(SafetyCheckRequest(user_id="u1", confidence=0.9))
    assert result.verdict == "proceed"


# ----------------------------------------------------------------- handoff --


def test_handoff_prefers_a_recorded_emergency_contact(monkeypatch):
    store = FakeMemoryStore(people=[{"name": "Aunty Bisi", "relation": "daughter", "roles": ["emergency"], "contact": "+234..."}])
    _wire(monkeypatch, store)

    result = safety_router.check_turn(SafetyCheckRequest(user_id="u1", utterance="chest pain"))

    assert result.handoff.source == "trusted_circle_emergency_contact"
    assert result.handoff.name == "Aunty Bisi"


def test_handoff_falls_back_to_the_national_emergency_number(monkeypatch):
    store = FakeMemoryStore(people=[])
    _wire(monkeypatch, store)

    result = safety_router.check_turn(SafetyCheckRequest(user_id="u1", utterance="chest pain"))

    assert result.handoff.source == "national_emergency_number"
    assert result.handoff.contact  # not empty


def test_mental_health_crisis_prefers_the_configured_hotline_over_the_national_number(monkeypatch):
    store = FakeMemoryStore(people=[])
    _wire(monkeypatch, store)
    monkeypatch.setattr(safety_router.get_settings(), "crisis_hotline_number", "0800-000-0000")

    result = safety_router.check_turn(SafetyCheckRequest(user_id="u1", utterance="I want to end my life"))

    assert result.handoff.source == "crisis_hotline"
    assert result.handoff.contact == "0800-000-0000"


# ------------------------------------------------- vetoing an in-progress action --


def test_crisis_phrase_vetoes_a_proposed_case_and_audits_it(monkeypatch):
    store = FakeMemoryStore()
    _wire(monkeypatch, store)
    case = store.create_case("u1", {"task": "medication_reorder", "state": "proposed", "data": {"med_id": "med-amlo"}})

    result = safety_router.check_turn(SafetyCheckRequest(user_id="u1", utterance="chest pain", case_id=case["id"]))

    assert result.vetoed_case_id == case["id"]
    assert store.cases[case["id"]]["state"] == "halted_by_safety_router"
    assert any(entry["action"] == "safety_router_veto" for entry in store.audit_log)


def test_veto_is_a_noop_when_the_case_is_already_resolved(monkeypatch):
    store = FakeMemoryStore()
    _wire(monkeypatch, store)
    case = store.create_case("u1", {"task": "medication_reorder", "state": "executed", "data": {}})

    result = safety_router.check_turn(SafetyCheckRequest(user_id="u1", utterance="chest pain", case_id=case["id"]))

    assert result.vetoed_case_id is None
    assert store.cases[case["id"]]["state"] == "executed"  # untouched


def test_veto_is_a_noop_without_a_case_id(monkeypatch):
    store = FakeMemoryStore()
    _wire(monkeypatch, store)

    result = safety_router.check_turn(SafetyCheckRequest(user_id="u1", utterance="chest pain"))
    assert result.vetoed_case_id is None


# ------------------------------- proves the veto actually stops Action, not just --
# ------------------------------- that Safety Router claims to have vetoed it --


def test_a_vetoed_case_genuinely_cannot_be_confirmed_by_action(monkeypatch):
    store = FakeMemoryStore(medication=AMLODIPINE, payment=PAYMENT)
    monkeypatch.setattr(reorder.memory_client, "get_medication", store.get_medication)
    monkeypatch.setattr(reorder.memory_client, "get_payment", store.get_payment)
    monkeypatch.setattr(reorder.memory_client, "list_people", store.list_people)
    monkeypatch.setattr(reorder.memory_client, "create_case", store.create_case)
    monkeypatch.setattr(reorder.memory_client, "get_case", store.get_case)
    monkeypatch.setattr(reorder.memory_client, "update_case", store.update_case)
    monkeypatch.setattr(reorder.memory_client, "append_audit", store.append_audit)
    monkeypatch.setattr(reorder.memory_client, "list_audit", store.list_audit)
    _wire(monkeypatch, store)

    proposal = reorder.propose_reorder(ReorderProposeRequest(user_id="u1", med_id="med-amlo"))
    assert store.cases[proposal.case_id]["state"] == "proposed"

    veto = safety_router.check_turn(
        SafetyCheckRequest(user_id="u1", utterance="I have chest pain", case_id=proposal.case_id)
    )
    assert veto.vetoed_case_id == proposal.case_id

    with pytest.raises(reorder.ReorderError):
        reorder.resolve_reorder(ReorderConfirmRequest(user_id="u1", case_id=proposal.case_id, confirmed=True))
