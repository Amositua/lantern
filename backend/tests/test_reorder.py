from datetime import datetime, timedelta, timezone

import pytest

from common.memory_client import MemoryAgentError
from services.action import reorder
from services.action.paystack_client import ChargeResult, PaystackError, SandboxPaystackClient
from services.action.pharmacy_client import OrderResult
from services.action.reorder_schemas import ReorderConfirmRequest, ReorderProposeRequest

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
    "method_ref": "AUTH_sandbox_abc123",
    "card_last4": "4242",
    "card_bank": "GTBank",
    "per_transaction_cap": 10000.0,  # naira -> 1,000,000 kobo, comfortably above the demo price
    "daily_cap": 20000.0,
    "never_auto_categories": [],
}


class FakePharmacyClient:
    def __init__(self, price_kobo=450000):
        self.price_kobo = price_kobo
        self.orders = []

    def get_refill_price(self, pharmacy_ref, name, dose):
        return self.price_kobo

    def place_order(self, pharmacy_ref, name, dose):
        self.orders.append((pharmacy_ref, name, dose))
        return OrderResult(order_id="order-test-1", amount_kobo=self.price_kobo, eta="2-3 days")


def _wire(monkeypatch, store, pharmacy=None, paystack=None):
    monkeypatch.setattr(reorder.memory_client, "get_medication", store.get_medication)
    monkeypatch.setattr(reorder.memory_client, "update_medication", store.update_medication)
    monkeypatch.setattr(reorder.memory_client, "get_payment", store.get_payment)
    monkeypatch.setattr(reorder.memory_client, "list_people", store.list_people)
    monkeypatch.setattr(reorder.memory_client, "create_case", store.create_case)
    monkeypatch.setattr(reorder.memory_client, "get_case", store.get_case)
    monkeypatch.setattr(reorder.memory_client, "update_case", store.update_case)
    monkeypatch.setattr(reorder.memory_client, "append_audit", store.append_audit)
    monkeypatch.setattr(reorder.memory_client, "list_audit", store.list_audit)
    monkeypatch.setattr(reorder, "get_pharmacy_client", lambda: pharmacy or FakePharmacyClient())
    monkeypatch.setattr(reorder, "get_paystack_client", lambda: paystack or SandboxPaystackClient())


def _familiar_store(**overrides):
    """A store where this med has one prior successful reorder, so
    familiarity alone doesn't force step-up in tests that aren't about that."""
    med = {**AMLODIPINE, **overrides.pop("medication", {})}
    payment = {**PAYMENT, **overrides.pop("payment", {})}
    prior_audit = [{"action": "medication_reorder", "result": "success", "proposed": {"med_id": med["id"]}}]
    return FakeMemoryStore(medication=med, payment=payment, audit=prior_audit, **overrides)


# ------------------------------------------------------------------ propose --


def test_propose_reads_back_identity_amount_payee_and_card(monkeypatch):
    store = _familiar_store()
    _wire(monkeypatch, store)

    proposal = reorder.propose_reorder(ReorderProposeRequest(user_id="u1", med_id="med-amlo"))

    assert "Amlodipine" in proposal.read_back
    assert "10mg" in proposal.read_back
    assert "pharmarun_demo" in proposal.read_back
    assert "4242" in proposal.read_back
    assert "₦4,500" in proposal.read_back
    assert proposal.amount_kobo == 450000
    assert store.cases[proposal.case_id]["state"] == "proposed"
    assert len(store.audit_log) == 1  # only the seeded prior reorder -- proposing itself logs nothing


def test_propose_rejects_a_medication_reordered_within_its_cadence(monkeypatch):
    recent = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
    store = _familiar_store(medication={"last_refill": recent})
    _wire(monkeypatch, store)

    with pytest.raises(reorder.DuplicateOrderError):
        reorder.propose_reorder(ReorderProposeRequest(user_id="u1", med_id="med-amlo"))


# --------------------------------------------------------- no charge without --
# --------------------------------------------------------- read-back + confirm --


def test_declining_does_not_charge_and_still_writes_audit(monkeypatch):
    store = _familiar_store()
    paystack = SandboxPaystackClient()
    _wire(monkeypatch, store, paystack=paystack)

    proposal = reorder.propose_reorder(ReorderProposeRequest(user_id="u1", med_id="med-amlo"))
    result = reorder.resolve_reorder(
        ReorderConfirmRequest(user_id="u1", case_id=proposal.case_id, confirmed=False)
    )

    assert result.status == "declined"
    assert paystack._charges == {}
    assert len(store.audit_log) == 2  # the seeded prior reorder, plus this decline
    assert store.audit_log[-1]["result"] == "declined"


def test_a_case_that_was_never_proposed_cannot_be_confirmed(monkeypatch):
    store = _familiar_store()
    _wire(monkeypatch, store)

    with pytest.raises(MemoryAgentError):
        reorder.resolve_reorder(ReorderConfirmRequest(user_id="u1", case_id="never-existed", confirmed=True))


def test_confirming_the_same_case_twice_is_rejected(monkeypatch):
    store = _familiar_store()
    _wire(monkeypatch, store)

    proposal = reorder.propose_reorder(ReorderProposeRequest(user_id="u1", med_id="med-amlo"))
    first = reorder.resolve_reorder(ReorderConfirmRequest(user_id="u1", case_id=proposal.case_id, confirmed=True))
    assert first.status == "executed"

    with pytest.raises(reorder.ReorderError):
        reorder.resolve_reorder(ReorderConfirmRequest(user_id="u1", case_id=proposal.case_id, confirmed=True))


# --------------------------------------------- verify-before-retry, no double-charge --


def test_simulated_timeout_does_not_double_charge(monkeypatch):
    store = _familiar_store(payment={"method_ref": "AUTH_timeout_once_xyz"})
    paystack = SandboxPaystackClient()
    _wire(monkeypatch, store, paystack=paystack)

    proposal = reorder.propose_reorder(ReorderProposeRequest(user_id="u1", med_id="med-amlo"))
    result = reorder.resolve_reorder(ReorderConfirmRequest(user_id="u1", case_id=proposal.case_id, confirmed=True))

    assert result.status == "executed"
    # the timeout path actually ran...
    assert proposal.idempotency_key in paystack._timed_out_once
    # ...but the ledger only ever recorded one charge for it
    assert list(paystack._charges.keys()) == [proposal.idempotency_key]


# ------------------------------------------------------- risk-scaled confirmation --


def test_over_cap_amount_requires_step_up_then_executes_with_a_token(monkeypatch):
    store = _familiar_store(payment={"per_transaction_cap": 4000.0})  # cap 400,000 kobo, price 450,000 kobo
    _wire(monkeypatch, store)

    proposal = reorder.propose_reorder(ReorderProposeRequest(user_id="u1", med_id="med-amlo"))
    assert proposal.required_confirmation == "step_up"

    blocked = reorder.resolve_reorder(ReorderConfirmRequest(user_id="u1", case_id=proposal.case_id, confirmed=True))
    assert blocked.status == "requires_step_up"

    proposal2 = reorder.propose_reorder(ReorderProposeRequest(user_id="u1", med_id="med-amlo"))
    executed = reorder.resolve_reorder(
        ReorderConfirmRequest(user_id="u1", case_id=proposal2.case_id, confirmed=True, step_up_token="123456")
    )
    assert executed.status == "executed"


def test_way_over_cap_requires_trusted_circle_not_just_step_up(monkeypatch):
    store = _familiar_store(
        payment={"per_transaction_cap": 100.0},  # cap 10,000 kobo; price 450,000 kobo is way past 2x that
        people=[{"name": "Aunty Bisi", "roles": ["trusted_circle"]}],
    )
    _wire(monkeypatch, store)

    proposal = reorder.propose_reorder(ReorderProposeRequest(user_id="u1", med_id="med-amlo"))
    assert proposal.required_confirmation == "trusted_circle"

    denied = reorder.resolve_reorder(
        ReorderConfirmRequest(user_id="u1", case_id=proposal.case_id, confirmed=True, confirmed_by="A Random Stranger")
    )
    assert denied.status == "requires_trusted_circle"

    proposal2 = reorder.propose_reorder(ReorderProposeRequest(user_id="u1", med_id="med-amlo"))
    approved = reorder.resolve_reorder(
        ReorderConfirmRequest(user_id="u1", case_id=proposal2.case_id, confirmed=True, confirmed_by="Aunty Bisi")
    )
    assert approved.status == "executed"


def test_never_auto_category_requires_step_up_even_under_cap_and_familiar(monkeypatch):
    store = _familiar_store(payment={"never_auto_categories": ["blood pressure"]})
    _wire(monkeypatch, store)

    proposal = reorder.propose_reorder(ReorderProposeRequest(user_id="u1", med_id="med-amlo"))
    assert proposal.required_confirmation == "step_up"


def test_first_time_reorder_of_a_med_requires_step_up_even_under_cap(monkeypatch):
    # no prior successful audit entry for this med -- unfamiliar
    store = FakeMemoryStore(medication=AMLODIPINE, payment=PAYMENT)
    _wire(monkeypatch, store)

    proposal = reorder.propose_reorder(ReorderProposeRequest(user_id="u1", med_id="med-amlo"))
    assert proposal.required_confirmation == "step_up"


def test_familiar_cheap_refill_needs_only_simple_confirmation(monkeypatch):
    store = _familiar_store()
    _wire(monkeypatch, store)

    proposal = reorder.propose_reorder(ReorderProposeRequest(user_id="u1", med_id="med-amlo"))
    assert proposal.required_confirmation == "simple"

    result = reorder.resolve_reorder(ReorderConfirmRequest(user_id="u1", case_id=proposal.case_id, confirmed=True))
    assert result.status == "executed"


# --------------------------------------------------- duplicate guard at confirm time --


def test_duplicate_guard_is_reevaluated_fresh_right_before_executing(monkeypatch):
    store = _familiar_store()
    _wire(monkeypatch, store)

    proposal = reorder.propose_reorder(ReorderProposeRequest(user_id="u1", med_id="med-amlo"))

    # something else reordered this med in the gap between propose and confirm
    store.medications["med-amlo"]["last_refill"] = datetime.now(timezone.utc).isoformat()

    result = reorder.resolve_reorder(ReorderConfirmRequest(user_id="u1", case_id=proposal.case_id, confirmed=True))
    assert result.status == "aborted_duplicate"


# --------------------------------------------------------------- audit coverage --


def test_every_branch_leaves_an_audit_record(monkeypatch):
    store = _familiar_store()
    _wire(monkeypatch, store)

    proposal = reorder.propose_reorder(ReorderProposeRequest(user_id="u1", med_id="med-amlo"))
    reorder.resolve_reorder(ReorderConfirmRequest(user_id="u1", case_id=proposal.case_id, confirmed=True))

    assert len(store.audit_log) == 2  # the seeded prior reorder, plus this one
    entry = store.audit_log[-1]
    assert entry["action"] == "medication_reorder"
    assert entry["result"] == "success"
    assert entry["idempotency_key"] == proposal.idempotency_key
    assert entry["proposed"]["med_id"] == "med-amlo"


def test_a_hard_paystack_failure_is_audited_and_surfaced(monkeypatch):
    class AlwaysFailsPaystack(SandboxPaystackClient):
        def charge_authorization(self, *args, **kwargs):
            raise PaystackError("card declined")

    store = _familiar_store()
    _wire(monkeypatch, store, paystack=AlwaysFailsPaystack())

    proposal = reorder.propose_reorder(ReorderProposeRequest(user_id="u1", med_id="med-amlo"))
    with pytest.raises(reorder.ReorderError):
        reorder.resolve_reorder(ReorderConfirmRequest(user_id="u1", case_id=proposal.case_id, confirmed=True))

    assert len(store.audit_log) == 2  # the seeded prior reorder, plus this failure
    assert "failed" in store.audit_log[-1]["result"]
