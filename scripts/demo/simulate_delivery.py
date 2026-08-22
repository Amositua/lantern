"""Stands in for a courier's own status webhooks. Reorders a fresh copy
of the seeded medication (so there's a real executed case, and a real
Pub/Sub "delivery started" publish to show in the Console), then steps
the order through preparing -> out for delivery -> delivered, each one
landing as its own activity-log entry.
"""
import time

from _client import ACTION_URL, DEMO_USER_ID, MEMORY_URL, call


def main() -> None:
    medications = call("GET", f"{MEMORY_URL}/users/{DEMO_USER_ID}/medications")
    if not medications:
        raise SystemExit("No medications on file -- run seed_demo_user.py first.")
    med_id = medications[0]["id"]

    print("1. Placing the order (this is what publishes to Pub/Sub) ...")
    proposal = call("POST", f"{ACTION_URL}/reorder/propose", {"user_id": DEMO_USER_ID, "med_id": med_id})
    result = call(
        "POST",
        f"{ACTION_URL}/reorder/confirm",
        {"user_id": DEMO_USER_ID, "case_id": proposal["case_id"], "confirmed": True, "step_up_token": "000000"},
    )
    if result["status"] != "executed":
        raise SystemExit(f"Reorder didn't execute (status={result['status']}) -- nothing to track.")
    order_id = result["order_id"]
    print(f"   order placed: {order_id}")

    for status in ("preparing", "out_for_delivery", "delivered"):
        time.sleep(1)
        print(f"\n2. Courier webhook: {status} ...")
        update = call(
            "POST",
            f"{ACTION_URL}/delivery/status",
            {"user_id": DEMO_USER_ID, "case_id": proposal["case_id"], "order_id": order_id, "status": status},
        )
        print(f"   {update['message']}")

    print("\nEach update landed as its own entry in the activity log.")


if __name__ == "__main__":
    main()
