"""Delivery status tracking over Pub/Sub. A successful reorder publishes
a "delivery started" event so the topic is genuinely visible in the
Console; status updates (simulated here, a real courier's own webhook in
production) get recorded against the case and the audit log. Read-only
from a Life Graph perspective -- this never re-triggers propose-confirm,
it only narrates what was already confirmed and paid for.
"""
import json
from typing import Optional

from common import memory_client
from common.logging_utils import get_logger

from .delivery_schemas import DeliveryStatusEvent, DeliveryStatusResult

logger = get_logger("action.delivery")


class DeliveryError(RuntimeError):
    pass


def publish_delivery_started(user_id: str, case_id: str, order_id: str) -> Optional[str]:
    """Best-effort, same as reengagement's refill-due publish -- Pub/Sub
    visibility is a nice-to-have here, not something the reorder itself
    should ever fail over."""
    try:
        from common.gcp_clients import get_pubsub_publisher, topic_path

        publisher = get_pubsub_publisher()
        path = topic_path("delivery-status")
        payload = json.dumps(
            {"user_id": user_id, "case_id": case_id, "order_id": order_id, "status": "preparing"}
        ).encode("utf-8")
        future = publisher.publish(path, payload)
        return future.result(timeout=5)
    except Exception:  # noqa: BLE001 - publishing is a nice-to-have here, not a dependency
        logger.warning("could not publish the delivery-started event to Pub/Sub", exc_info=True)
        return None


def record_delivery_status(event: DeliveryStatusEvent) -> DeliveryStatusResult:
    case = memory_client.get_case(event.user_id, event.case_id)
    if case.get("task") != "medication_reorder":
        raise DeliveryError(f"case {event.case_id} is not a medication reorder")
    if case.get("state") != "executed":
        raise DeliveryError(f"case {event.case_id} was never executed -- nothing to deliver")

    data = {**case.get("data", {}), "delivery_status": event.status, "order_id": event.order_id}
    memory_client.update_case(event.user_id, event.case_id, {"data": data})

    memory_client.append_audit(
        event.user_id,
        {
            "action": "medication_delivery",
            "proposed": {"order_id": event.order_id, "med_id": case.get("data", {}).get("med_id")},
            "confirmed_by": "pharmacy",
            "method": "delivery_webhook",
            "result": event.status,
        },
    )

    return DeliveryStatusResult(status=event.status, message=_message(event.status))


def _message(status: str) -> str:
    return {
        "preparing": "Your order is being prepared.",
        "out_for_delivery": "Your order is out for delivery.",
        "delivered": "Your order has been delivered.",
    }[status]
