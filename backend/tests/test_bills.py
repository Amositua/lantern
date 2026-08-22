from datetime import datetime, timedelta, timezone

import pytest

from common.memory_client import MemoryAgentError
from services.action import bills
from services.action.bills_schemas import BillConfirmRequest, BillProposeRequest
from services.action.paystack_client import PaystackError, SandboxPaystackClient
from services.action.utility_client import AccountStatement, PaymentResult

from .memory_fakes import FakeMemoryStore

EKEDC = {
    "id": "bill-ekedc",
    "provider": "EKEDC",
    "category": "electricity",
    "account_ref": "ACC-EKEDC-1",
    "last_paid": None,
}

PAYMENT = {
    "method_ref": "AUTH_sandbox_abc123",
    "card_last4": "4242",
    "card_bank": "GTBank",
    "per_transaction_cap": 10000.0,  # naira -> 1,000,000 kobo, comfortably above the demo price
    "daily_cap": 20000.0,
    "never_auto_categories": [],
}


class FakeUtilityClient:
    def __init__(self, amount_kobo=850000):
        self.amount_kobo = amount_kobo
        self.payments = []

    def get_account_statement(self, provider, account_ref):
        return AccountStatement(provider, "electricity", account_ref, self.amount_kobo, "the 28th")

    def get_amount_due(self, provider, account_ref):
        return self.amount_kobo

    def pay_bill(self, provider, account_ref, amount_kobo):
        self.payments.append((provider, account_ref, amount_kobo))
        return PaymentResult(reference="util-test-1", amount_kobo=amount_kobo)


def _wire(monkeypatch, store, utility=None, paystack=None):
    monkeypatch.setattr(bills.memory_client, "get_bill", store.get_bill)
    monkeypatch.setattr(bills.memory_client, "update_bill", store.update_bill)
    monkeypatch.setattr(bills.memory_client, "get_payment", store.get_payment)
    monkeypatch.setattr(bills.memory_client, "list_people", store.list_people)
    monkeypatch.setattr(bills.memory_client, "create_case", store.create_case)
    monkeypatch.setattr(bills.memory_client, "get_case", store.get_case)
    monkeypatch.setattr(bills.memory_client, "update_case", store.update_case)
    monkeypatch.setattr(bills.memory_client, "append_audit", store.append_audit)
    monkeypatch.setattr(bills.memory_client, "list_audit", store.list_audit)
    monkeypatch.setattr(bills, "get_utility_client", lambda: utility or FakeUtilityClient())
    monkeypatch.setattr(bills, "get_paystack_client", lambda: paystack or SandboxPaystackClient())


def _familiar_store(**overrides):
    bill = {**EKEDC, **overrides.pop("bill", {})}
    payment = {**PAYMENT, **overrides.pop("payment", {})}
    prior_audit = [{"action": "utility_bill_payment", "result": "success", "proposed": {"bill_id": bill["id"]}}]
    return FakeMemoryStore(bill=bill, payment=payment, audit=prior_audit, **overrides)


# ------------------------------------------------------------------ propose --


def test_propose_reads_back_provider_account_amount_and_card(monkeypatch):
    store = _familiar_store()
    _wire(monkeypatch, store)

    proposal = bills.propose_bill_payment(BillProposeRequest(user_id="u1", bill_id="bill-ekedc"))

    assert "EKEDC" in proposal.read_back
    assert "ACC-EKEDC-1" in proposal.read_back
    assert "4242" in proposal.read_back
    assert "₦8,500" in proposal.read_back
    assert proposal.amount_kobo == 850000
    assert store.cases[proposal.case_id]["state"] == "proposed"


def test_propose_rejects_a_bill_paid_within_the_last_day(monkeypatch):
    recent = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    store = _familiar_store(bill={"last_paid": recent})
    _wire(monkeypatch, store)

    with pytest.raises(bills.AlreadyPaidError):
        bills.propose_bill_payment(BillProposeRequest(user_id="u1", bill_id="bill-ekedc"))


# ----------------------------------------------------------- confirm / decline --


def test_declining_does_not_charge_and_still_writes_audit(monkeypatch):
    store = _familiar_store()
    paystack = SandboxPaystackClient()
    _wire(monkeypatch, store, paystack=paystack)

    proposal = bills.propose_bill_payment(BillProposeRequest(user_id="u1", bill_id="bill-ekedc"))
    result = bills.resolve_bill_payment(BillConfirmRequest(user_id="u1", case_id=proposal.case_id, confirmed=False))

    assert result.status == "declined"
    assert paystack._charges == {}


def test_a_case_that_was_never_proposed_cannot_be_confirmed(monkeypatch):
    store = _familiar_store()
    _wire(monkeypatch, store)

    with pytest.raises(MemoryAgentError):
        bills.resolve_bill_payment(BillConfirmRequest(user_id="u1", case_id="never-existed", confirmed=True))


# ----------------------------------------------- verify-before-retry, no double-charge --


def test_simulated_timeout_does_not_double_charge(monkeypatch):
    store = _familiar_store(payment={"method_ref": "AUTH_timeout_once_xyz"})
    paystack = SandboxPaystackClient()
    _wire(monkeypatch, store, paystack=paystack)

    proposal = bills.propose_bill_payment(BillProposeRequest(user_id="u1", bill_id="bill-ekedc"))
    result = bills.resolve_bill_payment(BillConfirmRequest(user_id="u1", case_id=proposal.case_id, confirmed=True))

    assert result.status == "executed"
    assert list(paystack._charges.keys()) == [proposal.idempotency_key]


# --------------------------------------------------------- risk-scaled confirmation --


def test_first_time_payment_of_a_bill_requires_step_up_even_under_cap(monkeypatch):
    store = FakeMemoryStore(bill=EKEDC, payment=PAYMENT)  # no prior successful payment -- unfamiliar
    _wire(monkeypatch, store)

    proposal = bills.propose_bill_payment(BillProposeRequest(user_id="u1", bill_id="bill-ekedc"))
    assert proposal.required_confirmation == "step_up"


def test_way_over_cap_requires_trusted_circle(monkeypatch):
    store = _familiar_store(
        payment={"per_transaction_cap": 100.0},  # cap 10,000 kobo; price 850,000 kobo is way past 2x that
        people=[{"name": "Aunty Bisi", "roles": ["trusted_circle"]}],
    )
    _wire(monkeypatch, store)

    proposal = bills.propose_bill_payment(BillProposeRequest(user_id="u1", bill_id="bill-ekedc"))
    assert proposal.required_confirmation == "trusted_circle"

    denied = bills.resolve_bill_payment(
        BillConfirmRequest(user_id="u1", case_id=proposal.case_id, confirmed=True, confirmed_by="A Random Stranger")
    )
    assert denied.status == "requires_trusted_circle"

    proposal2 = bills.propose_bill_payment(BillProposeRequest(user_id="u1", bill_id="bill-ekedc"))
    approved = bills.resolve_bill_payment(
        BillConfirmRequest(user_id="u1", case_id=proposal2.case_id, confirmed=True, confirmed_by="Aunty Bisi")
    )
    assert approved.status == "executed"


def test_familiar_bill_under_cap_needs_only_simple_confirmation(monkeypatch):
    store = _familiar_store()
    _wire(monkeypatch, store)

    proposal = bills.propose_bill_payment(BillProposeRequest(user_id="u1", bill_id="bill-ekedc"))
    assert proposal.required_confirmation == "simple"

    result = bills.resolve_bill_payment(BillConfirmRequest(user_id="u1", case_id=proposal.case_id, confirmed=True))
    assert result.status == "executed"


# ----------------------------------------------------- already-paid guard at confirm time --


def test_already_paid_guard_is_reevaluated_fresh_right_before_paying(monkeypatch):
    store = _familiar_store()
    _wire(monkeypatch, store)

    proposal = bills.propose_bill_payment(BillProposeRequest(user_id="u1", bill_id="bill-ekedc"))

    # something else paid this bill in the gap between propose and confirm
    store.bills["bill-ekedc"]["last_paid"] = datetime.now(timezone.utc).isoformat()

    result = bills.resolve_bill_payment(BillConfirmRequest(user_id="u1", case_id=proposal.case_id, confirmed=True))
    assert result.status == "aborted_already_paid"


def test_a_hard_paystack_failure_is_audited_and_surfaced(monkeypatch):
    class AlwaysFailsPaystack(SandboxPaystackClient):
        def charge_authorization(self, *args, **kwargs):
            raise PaystackError("card declined")

    store = _familiar_store()
    _wire(monkeypatch, store, paystack=AlwaysFailsPaystack())

    proposal = bills.propose_bill_payment(BillProposeRequest(user_id="u1", bill_id="bill-ekedc"))
    with pytest.raises(bills.BillPaymentError):
        bills.resolve_bill_payment(BillConfirmRequest(user_id="u1", case_id=proposal.case_id, confirmed=True))

    assert "failed" in store.audit_log[-1]["result"]
