import pytest

from common.memory_client import MemoryAgentError
from services.action import delivery
from services.action.delivery_schemas import DeliveryStatusEvent

from .memory_fakes import FakeMemoryStore


def _executed_reorder_case(store: FakeMemoryStore) -> str:
    case = store.create_case("u1", {"task": "medication_reorder", "state": "executed", "data": {"med_id": "med-amlo"}})
    return case["id"]


def _wire(monkeypatch, store):
    monkeypatch.setattr(delivery.memory_client, "get_case", store.get_case)
    monkeypatch.setattr(delivery.memory_client, "update_case", store.update_case)
    monkeypatch.setattr(delivery.memory_client, "append_audit", store.append_audit)


def test_recording_a_status_updates_the_case_and_writes_audit(monkeypatch):
    store = FakeMemoryStore()
    _wire(monkeypatch, store)
    case_id = _executed_reorder_case(store)

    result = delivery.record_delivery_status(
        DeliveryStatusEvent(user_id="u1", case_id=case_id, order_id="order-1", status="out_for_delivery")
    )

    assert result.status == "out_for_delivery"
    assert store.cases[case_id]["data"]["delivery_status"] == "out_for_delivery"
    assert store.cases[case_id]["data"]["med_id"] == "med-amlo"  # existing data preserved, not clobbered
    assert store.audit_log[-1]["action"] == "medication_delivery"
    assert store.audit_log[-1]["result"] == "out_for_delivery"


def test_sequential_status_updates_each_leave_their_own_audit_entry(monkeypatch):
    store = FakeMemoryStore()
    _wire(monkeypatch, store)
    case_id = _executed_reorder_case(store)

    for status in ("preparing", "out_for_delivery", "delivered"):
        delivery.record_delivery_status(
            DeliveryStatusEvent(user_id="u1", case_id=case_id, order_id="order-1", status=status)
        )

    assert len(store.audit_log) == 3
    assert store.cases[case_id]["data"]["delivery_status"] == "delivered"


def test_status_for_a_case_that_was_never_executed_is_rejected(monkeypatch):
    store = FakeMemoryStore()
    _wire(monkeypatch, store)
    case = store.create_case("u1", {"task": "medication_reorder", "state": "proposed", "data": {}})

    with pytest.raises(delivery.DeliveryError):
        delivery.record_delivery_status(
            DeliveryStatusEvent(user_id="u1", case_id=case["id"], order_id="order-1", status="preparing")
        )


def test_status_for_a_non_reorder_case_is_rejected(monkeypatch):
    store = FakeMemoryStore()
    _wire(monkeypatch, store)
    case = store.create_case("u1", {"task": "utility_bill_payment", "state": "executed", "data": {}})

    with pytest.raises(delivery.DeliveryError):
        delivery.record_delivery_status(
            DeliveryStatusEvent(user_id="u1", case_id=case["id"], order_id="order-1", status="preparing")
        )


def test_status_for_a_missing_case_surfaces_the_memory_error(monkeypatch):
    store = FakeMemoryStore()
    _wire(monkeypatch, store)

    with pytest.raises(MemoryAgentError):
        delivery.record_delivery_status(
            DeliveryStatusEvent(user_id="u1", case_id="never-existed", order_id="order-1", status="preparing")
        )
