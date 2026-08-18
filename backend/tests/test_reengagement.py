from datetime import datetime, timedelta, timezone

import pytest

from services.action import reengagement, reorder
from services.action.paystack_client import SandboxPaystackClient
from services.action.pharmacy_client import OrderResult
from services.action.reengagement_schemas import ReengagementFireRequest

from .memory_fakes import FakeMemoryStore

NOW = datetime.now(timezone.utc)

AMLODIPINE = {
    "id": "med-amlo",
    "name": "Amlodipine",
    "dose": "10mg",
    "condition": "blood pressure",
    "pharmacy_ref": "pharmarun_demo",
    "cadence": 30,
    "last_refill": None,
    "last_confirmed": (NOW - timedelta(days=10)).isoformat(),
    "discontinued": False,
}

METFORMIN = {
    "id": "med-metf",
    "name": "Metformin",
    "dose": "500mg",
    "condition": "diabetes",
    "pharmacy_ref": "pharmarun_demo",
    "cadence": 30,
    "last_refill": (NOW - timedelta(days=40)).isoformat(),  # overdue -> "also due"
    "last_confirmed": (NOW - timedelta(days=10)).isoformat(),
}

PAYMENT = {
    "method_ref": "AUTH_sandbox_abc",
    "card_last4": "4242",
    "per_transaction_cap": 10000.0,
    "daily_cap": 20000.0,
    "never_auto_categories": [],
}


class FakePharmacyClient:
    def get_refill_price(self, pharmacy_ref, name, dose):
        return 450000

    def place_order(self, pharmacy_ref, name, dose):
        return OrderResult(order_id="order-test-1", amount_kobo=450000, eta="2-3 days")


def _wire(monkeypatch, store):
    monkeypatch.setattr(reengagement.memory_client, "get_medication", store.get_medication)
    monkeypatch.setattr(reengagement.memory_client, "list_medications", store.list_medications)
    monkeypatch.setattr(reengagement.memory_client, "list_cases", store.list_cases)
    monkeypatch.setattr(reengagement.memory_client, "create_case", store.create_case)
    monkeypatch.setattr(reengagement.memory_client, "update_case", store.update_case)
    monkeypatch.setattr(reengagement.memory_client, "append_audit", store.append_audit)
    monkeypatch.setattr(reengagement.memory_client, "list_people", store.list_people)
    monkeypatch.setattr(reengagement.memory_client, "get_life_graph", store.get_life_graph)

    # reengagement delegates to reorder.propose_reorder for the actual proposal
    monkeypatch.setattr(reorder.memory_client, "get_medication", store.get_medication)
    monkeypatch.setattr(reorder.memory_client, "get_payment", store.get_payment)
    monkeypatch.setattr(reorder.memory_client, "list_people", store.list_people)
    monkeypatch.setattr(reorder.memory_client, "create_case", store.create_case)
    monkeypatch.setattr(reorder.memory_client, "get_case", store.get_case)
    monkeypatch.setattr(reorder.memory_client, "update_case", store.update_case)
    monkeypatch.setattr(reorder.memory_client, "append_audit", store.append_audit)
    monkeypatch.setattr(reorder.memory_client, "list_audit", store.list_audit)
    monkeypatch.setattr(reorder, "get_pharmacy_client", lambda: FakePharmacyClient())
    monkeypatch.setattr(reorder, "get_paystack_client", lambda: SandboxPaystackClient())


def _daytime_profile():
    # avoid the default quiet-hours window landing on whatever hour the
    # test happens to run at -- explicit, always-open hours
    return {"quiet_hours_start": 3, "quiet_hours_end": 4}


# ------------------------------------------------------------- stale abort --


def test_rx_changed_since_scheduling_aborts_the_reorder(monkeypatch):
    store = FakeMemoryStore(medication=AMLODIPINE, payment=PAYMENT, profile=_daytime_profile())
    _wire(monkeypatch, store)

    scheduled_at = NOW - timedelta(hours=1)
    # the Rx got touched *after* scheduling, e.g. a dose change behind the scenes
    store.medications["med-amlo"]["last_confirmed"] = NOW.isoformat()

    result = reengagement.evaluate_and_reengage(
        ReengagementFireRequest(user_id="u1", med_id="med-amlo", scheduled_at=scheduled_at)
    )

    assert result.status == "aborted_rx_changed"
    assert result.case_id is None
    assert result.proposal is None
    assert store.cases == {}  # propose_reorder was never reached


def test_discontinued_medication_aborts(monkeypatch):
    med = {**AMLODIPINE, "discontinued": True}
    store = FakeMemoryStore(medication=med, payment=PAYMENT, profile=_daytime_profile())
    _wire(monkeypatch, store)

    result = reengagement.evaluate_and_reengage(ReengagementFireRequest(user_id="u1", med_id="med-amlo"))
    assert result.status == "aborted_discontinued"
    assert store.cases == {}


def test_already_reordered_aborts_as_a_duplicate(monkeypatch):
    med = {**AMLODIPINE, "last_refill": (NOW - timedelta(days=2)).isoformat()}  # well within cadence
    store = FakeMemoryStore(medication=med, payment=PAYMENT, profile=_daytime_profile())
    _wire(monkeypatch, store)

    result = reengagement.evaluate_and_reengage(ReengagementFireRequest(user_id="u1", med_id="med-amlo"))
    assert result.status == "aborted_already_reordered"
    assert store.cases == {}


# --------------------------------------------------------- valid -> propose --


def test_a_valid_event_routes_to_propose_confirm(monkeypatch):
    store = FakeMemoryStore(medication=AMLODIPINE, payment=PAYMENT, profile=_daytime_profile())
    _wire(monkeypatch, store)

    result = reengagement.evaluate_and_reengage(ReengagementFireRequest(user_id="u1", med_id="med-amlo"))

    assert result.status == "proposed"
    assert result.proposal is not None
    assert result.case_id is not None
    assert store.cases[result.case_id]["state"] == "nudged"
    assert store.cases[result.case_id]["task"] == "medication_reengagement"

    # the actual reorder proposal is a real, separate, confirmable case
    reorder_case_id = result.proposal.case_id
    assert store.cases[reorder_case_id]["state"] == "proposed"


def test_valid_event_consolidates_other_due_medications_into_one_message(monkeypatch):
    store = FakeMemoryStore(medications=[AMLODIPINE, METFORMIN], payment=PAYMENT, profile=_daytime_profile())
    _wire(monkeypatch, store)

    result = reengagement.evaluate_and_reengage(ReengagementFireRequest(user_id="u1", med_id="med-amlo"))

    assert result.also_due == ["Metformin"]
    assert "Metformin" in result.message


def test_quiet_hours_defers_instead_of_reaching_out(monkeypatch):
    store = FakeMemoryStore(medication=AMLODIPINE, payment=PAYMENT, profile={"quiet_hours_start": 0, "quiet_hours_end": 23})
    _wire(monkeypatch, store)

    result = reengagement.evaluate_and_reengage(ReengagementFireRequest(user_id="u1", med_id="med-amlo"))

    assert result.status == "deferred_quiet_hours"
    assert store.cases == {}


# -------------------------------------------------- anti-nag: backoff/escalate --


def test_unanswered_nudges_escalate_to_trusted_circle_instead_of_repeating(monkeypatch):
    store = FakeMemoryStore(
        medication=AMLODIPINE,
        payment=PAYMENT,
        profile=_daytime_profile(),
        people=[{"name": "Aunty Bisi", "roles": ["trusted_circle"]}],
    )
    _wire(monkeypatch, store)

    results = []
    for _ in range(4):
        results.append(reengagement.evaluate_and_reengage(ReengagementFireRequest(user_id="u1", med_id="med-amlo")))

    # first three nudge, with an increasing (not repeated) count on the *same* case
    assert [r.status for r in results[:3]] == ["proposed", "proposed", "proposed"]
    assert len(store.cases) == 1 + 3  # one reengagement case, reused, plus one reorder case per nudge
    reengagement_cases = [c for c in store.cases.values() if c["task"] == "medication_reengagement"]
    assert len(reengagement_cases) == 1
    # nudge_count reflects all 4 calls by now, including the escalating one --
    # the point being proven is there's still just one case, updated in place,
    # not four separate identical nudges
    assert reengagement_cases[0]["data"]["nudge_count"] == 4

    # the fourth stops nudging the user and hands off instead
    assert results[3].status == "escalated_to_trusted_circle"
    assert "Aunty Bisi" in results[3].message
    assert reengagement_cases[0]["state"] == "escalated_to_trusted_circle"


def test_escalation_still_writes_an_audit_record_even_though_nothing_executes(monkeypatch):
    store = FakeMemoryStore(
        medication=AMLODIPINE, payment=PAYMENT, profile=_daytime_profile(), people=[{"name": "Aunty Bisi", "roles": ["caregiver"]}]
    )
    _wire(monkeypatch, store)

    for _ in range(4):
        reengagement.evaluate_and_reengage(ReengagementFireRequest(user_id="u1", med_id="med-amlo"))

    escalation_entries = [e for e in store.audit_log if e["result"] == "escalated_to_trusted_circle"]
    assert len(escalation_entries) == 1
