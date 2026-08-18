import pytest

from services.memory import life_graph as lg
from services.memory.schemas import (
    CasePatch,
    CaseWrite,
    MedicationCreate,
    MedicationPatch,
    MedicationVerification,
    PaymentVerification,
    PaymentWrite,
    PreferenceWrite,
)

from .fake_firestore import FakeFirestoreClient


@pytest.fixture
def db():
    return FakeFirestoreClient()


def _verified() -> MedicationVerification:
    return MedicationVerification(method="prescription_verified", verified_by="Dr. Adeyemi", rx_ref="RX-1")


# ------------------------------------------------------ tiered write-trust --


def test_medication_create_without_verification_is_rejected_by_schema():
    with pytest.raises(Exception):
        MedicationCreate(name="Amlodipine", dose="10mg")  # missing required verification block


def test_dose_change_outside_enrollment_path_is_rejected(db):
    created = lg.create_medication(
        "u1", MedicationCreate(name="Amlodipine", dose="10mg", verification=_verified()), db=db
    )

    with pytest.raises(lg.TrustViolation):
        lg.update_medication("u1", created["id"], MedicationPatch(dose="20mg"), db=db)

    unchanged = lg.get_medication("u1", created["id"], db=db)
    assert unchanged["dose"] == "10mg"


def test_dose_change_with_verification_is_allowed(db):
    created = lg.create_medication(
        "u1", MedicationCreate(name="Amlodipine", dose="10mg", verification=_verified()), db=db
    )
    updated = lg.update_medication(
        "u1", created["id"], MedicationPatch(dose="20mg", verification=_verified()), db=db
    )
    assert updated["dose"] == "20mg"


def test_non_identity_field_can_change_without_verification(db):
    created = lg.create_medication(
        "u1", MedicationCreate(name="Amlodipine", dose="10mg", verification=_verified()), db=db
    )
    updated = lg.update_medication("u1", created["id"], MedicationPatch(cadence=30), db=db)
    assert updated["cadence"] == 30


# -------------------------------------------------------- preference tiers --


def test_first_time_preference_is_provisional(db):
    result = lg.write_preference(
        "u1",
        PreferenceWrite(domain="pack_size", value="small", source_utterance="just get the small pack", is_override=False),
        db=db,
    )
    assert result["applied"] is True
    assert result["reason"] == "provisional_created"
    assert result["standing_preference"]["confidence"] < lg.HARDENED_CONFIDENCE
    assert result["standing_preference"]["observation_count"] == 1


def test_one_off_override_never_becomes_the_standing_belief(db):
    lg.write_preference(
        "u1",
        PreferenceWrite(domain="pack_size", value="small", source_utterance="usually the small pack", is_override=False),
        db=db,
    )
    result = lg.write_preference(
        "u1",
        PreferenceWrite(domain="pack_size", value="large", source_utterance="just this once, get the big one", is_override=True),
        db=db,
    )
    assert result["applied"] is False
    assert result["reason"] == "one_off_override"

    standing = lg.list_preferences("u1", db=db)
    assert len(standing) == 1
    assert standing[0]["value"] == "small"


def test_repeated_confirmation_hardens_a_preference(db):
    for _ in range(lg.HARDENED_OBSERVATIONS):
        result = lg.write_preference(
            "u1",
            PreferenceWrite(domain="pack_size", value="small", source_utterance="small pack again", is_override=False),
            db=db,
        )
    assert result["standing_preference"]["hardened"] is True


def test_contradiction_on_a_hardened_preference_raises_a_resolution_event_instead_of_overwriting(db):
    for _ in range(lg.HARDENED_OBSERVATIONS):
        lg.write_preference(
            "u1",
            PreferenceWrite(domain="pack_size", value="small", source_utterance="small pack again", is_override=False),
            db=db,
        )

    result = lg.write_preference(
        "u1",
        PreferenceWrite(domain="pack_size", value="large", source_utterance="actually I want the big pack now", is_override=False),
        db=db,
    )

    assert result["applied"] is False
    assert result["reason"] == "contradiction"
    assert result["standing_preference"]["value"] == "small"  # untouched

    events = lg.list_resolution_events("u1", db=db)
    assert len(events) == 1
    assert events[0]["new_value"] == "large"
    assert events[0]["existing_value"] == "small"
    assert events[0]["status"] == "pending"


def test_correction_of_a_still_provisional_preference_does_not_need_resolution(db):
    lg.write_preference(
        "u1",
        PreferenceWrite(domain="pack_size", value="small", source_utterance="small pack", is_override=False),
        db=db,
    )
    result = lg.write_preference(
        "u1",
        PreferenceWrite(domain="pack_size", value="large", source_utterance="no wait, the big pack", is_override=False),
        db=db,
    )
    assert result["applied"] is True
    assert result["reason"] == "provisional_revised"
    assert result["standing_preference"]["value"] == "large"
    assert len(lg.list_resolution_events("u1", db=db)) == 0


def test_resolving_a_contradiction_toward_the_new_value_updates_the_standing_belief(db):
    for _ in range(lg.HARDENED_OBSERVATIONS):
        lg.write_preference(
            "u1",
            PreferenceWrite(domain="pack_size", value="small", source_utterance="small pack again", is_override=False),
            db=db,
        )
    contradiction = lg.write_preference(
        "u1",
        PreferenceWrite(domain="pack_size", value="large", source_utterance="actually the big pack now", is_override=False),
        db=db,
    )
    event_id = contradiction["resolution_event"]["id"]

    from services.memory.schemas import ResolutionEventResolve

    lg.resolve_resolution_event(
        "u1", event_id, ResolutionEventResolve(decision="accept_new", resolved_by="user"), db=db
    )

    standing = lg.list_preferences("u1", db=db)
    assert standing[0]["value"] == "large"
    assert lg.list_resolution_events("u1", db=db) == []


# ----------------------------------------------------------- payment + cases --


def test_get_payment_returns_the_unredacted_method_ref(db):
    lg.write_payment(
        "u1",
        PaymentWrite(
            method_ref="AUTH_real_token_123",
            per_transaction_cap=5000,
            daily_cap=10000,
            verification=PaymentVerification(method="paystack_first_transaction_2fa"),
        ),
        db=db,
    )
    payment = lg.get_payment("u1", db=db)
    assert payment["method_ref"] == "AUTH_real_token_123"


def test_get_payment_is_none_when_nothing_enrolled(db):
    assert lg.get_payment("u1", db=db) is None


def test_case_data_field_round_trips_through_create_and_update(db):
    case = lg.create_case(
        "u1",
        CaseWrite(task="medication_reorder", state="proposed", data={"med_id": "med-amlo", "amount_kobo": 450000}),
        db=db,
    )
    assert case["data"]["med_id"] == "med-amlo"

    updated = lg.update_case("u1", case["id"], CasePatch(state="executed"), db=db)
    assert updated["state"] == "executed"
    assert updated["data"]["amount_kobo"] == 450000  # untouched by a patch that doesn't set data
